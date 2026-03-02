import os
import csv
import webbrowser
import concurrent.futures
import re
from PyQt5 import QtWidgets, QtCore, QtGui
from lib.validators import is_valid_email_syntax, has_mx_record, verify_email_smtp
import pandas as pd


def clean_smtp_message(message):
    """Clean SMTP message by removing enhanced status code prefixes like \n5.1.1"""
    if not message:
        return message
    # Remove newlines followed by status code pattern (e.g., \n5.1.1, \n4.2.0)
    cleaned = re.sub(r'\n\d+\.\d+\.\d+\s*', ' ', message)
    # Also remove status code at the beginning of the message
    cleaned = re.sub(r'^\d+\.\d+\.\d+\s*', '', cleaned)
    # Replace remaining newlines with spaces
    cleaned = cleaned.replace('\\n', ' ')
    cleaned = cleaned.replace('\n', ' ')
    # Normalize whitespace
    cleaned = ' '.join(cleaned.split())
    return cleaned

class ResultDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Verifying Bulk Emails...")
        self.setMinimumSize(600, 400)
        self.layout = QtWidgets.QVBoxLayout()

        # Status bar: elapsed time + progress count
        self.status_label = QtWidgets.QLabel("⏱ 0:00:00  |  0 / 0 verified")
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        font = self.status_label.font()
        font.setBold(True)
        self.status_label.setFont(font)
        self.layout.addWidget(self.status_label)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Email", "Status", "SMTP Message"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.table.setColumnWidth(0, 250)  # Make email column wider
        
        self.layout.addWidget(self.table)
        self.setLayout(self.layout)


    # Enable the "?" help button
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowContextHelpButtonHint)

        

    def add_row(self, email, status, smtp_message=""):
        row_position = self.table.rowCount()
        self.table.insertRow(row_position)
        
        email_item = QtWidgets.QTableWidgetItem(email)
        status_item = QtWidgets.QTableWidgetItem(status)
        smtp_item = QtWidgets.QTableWidgetItem(smtp_message)
        
        if status == "Valid":
            status_item.setForeground(QtGui.QColor('#27ae60'))  # Green
        elif status.startswith("Invalid"):
            status_item.setForeground(QtGui.QColor('#e74c3c'))  # Red
        else:
            status_item.setForeground(QtGui.QColor('#f1c40f'))  # Yellow
        
        self.table.setItem(row_position, 0, email_item)
        self.table.setItem(row_position, 1, status_item)
        self.table.setItem(row_position, 2, smtp_item)

    def update_status(self, elapsed_str, done, total):
        self.status_label.setText(f"⏱ {elapsed_str}  |  {done} / {total} verified")
    
    def showEvent(self, event):
        """Override showEvent to ensure the help button is available."""
        super().showEvent(event)
        
        # Find the help button after the dialog is shown
        help_button = self.findChild(QtWidgets.QAbstractButton, "qt_help_button")
        if help_button:
            help_button.clicked.connect(self.show_status_help)

    def show_status_help(self):
        help_text = """
        <b>Verification Status Explanations:</b><br><br>
        
        <span style='color:#27ae60; font-weight:bold'>Valid</span>: 
        - Email address is valid and reachable<br>
        - Domain has proper MX records<br>
        - SMTP server confirmed the mailbox exists<br><br>
        
        <span style='color:#e74c3c; font-weight:bold'>Invalid (Syntax)</span>: 
        - Email format is incorrect<br>
        - Missing @ symbol or invalid domain structure<br>
        - Example: <i>user@domain</i> (missing .com)<br><br>
        
        <span style='color:#e74c3c; font-weight:bold'>Invalid (No MX)</span>: 
        - Domain does not have mail exchange records<br>
        - Domain might not exist or is not configured for email<br>
        - Example: <i>user@nonexistentdomain.xyz</i><br><br>
        
        <span style='color:#e74c3c; font-weight:bold'>Invalid (SMTP)</span>: 
        - Domain exists, but the mailbox does not<br>
        - SMTP server rejected the recipient address<br>
        - Example: <i>nonexistentuser@gmail.com</i><br><br>
        
        <span style='color:#f1c40f; font-weight:bold'>Error</span>: 
        - Temporary network issues<br>
        - SMTP server timeout or connection error<br>
        - Unexpected verification errors<br><br>
        
        <i>Note: Some email servers may block verification attempts for privacy reasons.</i>
        """
        help_dialog = QtWidgets.QMessageBox(self)
        help_dialog.setWindowTitle("Verification Status Help")
        help_dialog.setTextFormat(QtCore.Qt.RichText)  # Enable HTML formatting
        help_dialog.setText(help_text)
        help_dialog.setStandardButtons(QtWidgets.QMessageBox.Ok)
        help_dialog.exec_()

class SingleVerificationWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal(str, bool, str)

    def __init__(self, email):
        super().__init__()
        self.email = email

    def run(self):
        try:
            domain = self.email.split('@')[1]
            if not has_mx_record(domain):
                self.finished.emit("Domain does not have MX records", False)
                return

            is_valid, smtp_message = verify_email_smtp(self.email)
            if not is_valid:
                self.finished.emit(f"SMTP verification failed: {smtp_message}", False, smtp_message)
            else:
                self.finished.emit(f"Email is valid and appears to be reachable: {smtp_message}", True, smtp_message)
        except Exception as e:
            self.finished.emit(f"Error: {str(e)}", False, str(e))

class BulkVerificationThread(QtCore.QThread):
    result_signal = QtCore.pyqtSignal(str, str, str)
    all_done = QtCore.pyqtSignal()
    
    def __init__(self, emails):
        super().__init__()
        self.emails = emails
        self.is_running = True
        
    def run(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
            future_to_email = {executor.submit(self.verify_single_email, email): email for email in self.emails if email}
            
            for future in concurrent.futures.as_completed(future_to_email):
                if not self.is_running:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                    
                email = future_to_email[future]
                try:
                    status, smtp_message = future.result()
                except Exception as e:
                    status = f"Error: {str(e)}"
                    smtp_message = str(e)
                
                self.result_signal.emit(email, status, smtp_message)
                
        if self.is_running:
            self.all_done.emit()

    def verify_single_email(self, email):
        try:
            if not is_valid_email_syntax(email):
                return "Invalid (Syntax)", "Email syntax validation failed"
            
            domain = email.split('@')[1]
            if not has_mx_record(domain):
                return "Invalid (No MX)", "Domain does not have MX records"
            
            is_valid, smtp_message = verify_email_smtp(email)
            if not is_valid:
                return "Invalid (SMTP)", smtp_message
            
            return "Valid", smtp_message
        except Exception as e:
            return f"Error: {str(e)}", str(e)

    def stop(self):
        self.is_running = False

class EmailValidatorApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.apply_styles()
        self.verifying_timer = QtCore.QTimer()
        self.verifying_counter = 1
        self.verifying_timer.timeout.connect(self.update_verifying_text)
        self.bulk_thread = None
        self.single_worker_thread = None

        # Stopwatch for bulk verification
        self._elapsed_timer = QtCore.QTimer()
        self._elapsed_timer.timeout.connect(self._update_elapsed_time)
        self._elapsed_seconds = 0
        self._total_emails = 0
        self._verified_count = 0

    def init_ui(self):
        self.setWindowTitle("KnowEmail")
        self.setMinimumSize(600, 500)
        
        # Set window icon
        current_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(current_dir, '..', 'favicon.ico')
        self.setWindowIcon(QtGui.QIcon(icon_path))

        # Main layout
        main_layout = QtWidgets.QVBoxLayout()
        main_layout.setContentsMargins(40, 30, 40, 30)
        main_layout.setSpacing(15)

        # Header Section
        header_layout = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel("KnowEmail")
        title.setObjectName("title")
        
        subtitle = QtWidgets.QLabel("Ad-Free & Open Source Bulk Email Verifier")
        subtitle.setObjectName("subtitle")
        
        header_layout.addWidget(title, 0, QtCore.Qt.AlignHCenter)
        header_layout.addWidget(subtitle, 0, QtCore.Qt.AlignHCenter)
        main_layout.addLayout(header_layout)

        description = QtWidgets.QLabel(
            "Tired of dealing with invalid email addresses? KnowEmail helps you "
            "clean your email lists by ensuring every address is valid before you send that "
            "important campaign."
        )
        description.setWordWrap(True)
        description.setObjectName("description")
        main_layout.addWidget(description)

        # Input Section
        input_layout = QtWidgets.QHBoxLayout()
        self.email_input = QtWidgets.QLineEdit()
        self.email_input.setPlaceholderText("Enter Email Address")
        self.email_input.setObjectName("emailInput")
        
        self.validate_button = QtWidgets.QPushButton("Check")
        self.validate_button.setObjectName("checkButton")
        self.validate_button.clicked.connect(self.validate_email)
        
        input_layout.addWidget(self.email_input)
        input_layout.addWidget(self.validate_button)
        main_layout.addLayout(input_layout)

        # Result Label
        self.result_label = QtWidgets.QLabel("")
        self.result_label.setObjectName("resultLabel")
        main_layout.addWidget(self.result_label)

        # Bulk Verify Button
        self.bulk_button = QtWidgets.QPushButton("Check Multiple Emails")
        self.bulk_button.setObjectName("bulkButton")
        self.bulk_button.clicked.connect(self.bulk_verify)
        main_layout.addWidget(self.bulk_button)

        # Support Section
        support_layout = QtWidgets.QVBoxLayout()
        support_label = QtWidgets.QLabel(
            "We've made this tool free and open-source for everyone."
            "If you'd like to support our development efforts, consider donating."
        )
        support_label.setWordWrap(True)
        support_label.setObjectName("supportLabel")
        
        donate_button = QtWidgets.QPushButton("Support Us")
        donate_button.setObjectName("donateButton")
        donate_button.clicked.connect(lambda: webbrowser.open("https://example.com/donate"))
        
        support_layout.addWidget(support_label, 0, QtCore.Qt.AlignHCenter)
        support_layout.addWidget(donate_button, 0, QtCore.Qt.AlignHCenter)
        main_layout.addLayout(support_layout)

        # Add spacer to push support section to bottom
        main_layout.addStretch(1)

        self.setLayout(main_layout)

    def bulk_verify(self):
        file_dialog = QtWidgets.QFileDialog()
        file_path, _ = file_dialog.getOpenFileName(
            self,
            "Select Email List",
            "",
            "Text File (*.txt);; Excel File (*.xlsx)"
        )
        
        if not file_path:
            return
            
        try:
            if file_path.endswith('.txt'):
                with open(file_path, 'r') as f:
                    emails = [line.strip() for line in f.readlines() if line.strip()]
            elif file_path.endswith('.xlsx'):
                df = pd.read_excel(file_path)
                emails = df.iloc[:, 0].astype(str).tolist()
            else:
                raise ValueError("Unsupported file format")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to read file: {str(e)}")
            return
            
        if hasattr(self, 'results_dialog'):
            try:
                self.results_dialog.finished.disconnect(self._elapsed_timer.stop)
            except TypeError:
                pass  # already disconnected

        self.results_dialog = ResultDialog(self)
        self.results_dialog.finished.connect(self._elapsed_timer.stop)
        self.results_dialog.show()
        self._bulk_results = []
        self._smtp_messages = []

        # Start verification in background
        if self.bulk_thread and self.bulk_thread.isRunning():
             self.bulk_thread.stop()
             self.bulk_thread.wait()

        self._total_emails = len(emails)
        self._verified_count = 0
        self._elapsed_seconds = 0
        self._elapsed_timer.start(1000)

        self.bulk_thread = BulkVerificationThread(emails)
        self.bulk_thread.result_signal.connect(self.update_results, QtCore.Qt.QueuedConnection)
        self.bulk_thread.all_done.connect(self.on_bulk_all_done)
        self.bulk_thread.start()

    def on_bulk_all_done(self):
        self._elapsed_timer.stop()
        h = self._elapsed_seconds // 3600
        m = (self._elapsed_seconds % 3600) // 60
        s = self._elapsed_seconds % 60
        elapsed_str = f"{h}:{m:02d}:{s:02d}"
        reply = QtWidgets.QMessageBox.question(
            self,
            "Process Complete",
            f"All {self._total_emails} emails have been checked!\n"
            f"⏱ Total time: {elapsed_str}\n\n"
            f"Would you like to export the results to CSV?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self.export_bulk_results_csv()

    def export_bulk_results_csv(self):
        if not self._bulk_results:
            return

        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Verification Results",
            "email_verification_results.csv",
            "CSV File (*.csv)"
        )

        if not file_path:
            return

        try:
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Email", "Status", "SMTP Message"])
                # Combine results with SMTP messages
                combined_results = [
                    (email, status, smtp_msg) 
                    for (email, status), smtp_msg in zip(self._bulk_results, self._smtp_messages)
                ]
                writer.writerows(combined_results)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Export Error", f"Failed to save CSV: {str(e)}")

    def update_results(self, email, status, smtp_message):
        self._bulk_results.append((email, status))
        # Clean the SMTP message for display
        clean_message = clean_smtp_message(smtp_message)
        self._smtp_messages.append(clean_message)
        self.results_dialog.add_row(email, status, clean_message)
        self._verified_count += 1
        self._refresh_status_label()

    def _update_elapsed_time(self):
        self._elapsed_seconds += 1
        self._refresh_status_label()

    def _refresh_status_label(self):
        h = self._elapsed_seconds // 3600
        m = (self._elapsed_seconds % 3600) // 60
        s = self._elapsed_seconds % 60
        elapsed_str = f"{h}:{m:02d}:{s:02d}"
        if getattr(self, 'results_dialog', None) and self.results_dialog.isVisible():
            self.results_dialog.update_status(elapsed_str, self._verified_count, self._total_emails)

    def apply_styles(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        style_path = os.path.join(current_dir, 'styles.qss')
        with open(style_path, 'r') as f:
            self.setStyleSheet(f.read())

    def update_verifying_text(self):
        self.result_label.setText(f"Verifying{'.' * self.verifying_counter}")
        self.verifying_counter = (self.verifying_counter % 3) + 1

    def validate_email(self):
        email = self.email_input.text()
        if not email:
            QtWidgets.QMessageBox.warning(self, "Error", "Email parameter is required")
            return
        if not is_valid_email_syntax(email):
            QtWidgets.QMessageBox.warning(self, "Error", "Invalid email syntax")
            return
            
        self.verifying_counter = 1
        self.verifying_timer.start(500)
        self.result_label.setText("Verifying...")
        self.validate_button.setEnabled(False)
        self.email_input.setEnabled(False)

        # Create worker and thread for async execution
        self.single_worker_thread = QtCore.QThread()
        self.worker = SingleVerificationWorker(email)
        self.worker.moveToThread(self.single_worker_thread)
        
        # Connect signals
        self.single_worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.handle_single_verification_result)
        self.worker.finished.connect(self.single_worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.single_worker_thread.finished.connect(self.single_worker_thread.deleteLater)
        
        self.single_worker_thread.start()

    def handle_single_verification_result(self, message, is_valid, smtp_message):
        self.verifying_timer.stop()
        self.result_label.setText("")
        self.validate_button.setEnabled(True)
        self.email_input.setEnabled(True)
        
        # Clean the SMTP message for display
        clean_message = clean_smtp_message(smtp_message)
        # Show status and cleaned message
        if is_valid:
            display_msg = 'Email is valid and appears to be reachable\n\n' + clean_message
        else:
            display_msg = 'Email verification failed.\n\n' + 'Reason: ' + clean_message
        self.show_popup(display_msg)

    def show_popup(self, message):
        self.verifying_timer.stop()
        self.result_label.setText("")
    
        msg = QtWidgets.QMessageBox(self)
        msg.setIcon(QtWidgets.QMessageBox.Information)
        msg.setText(message)
        msg.setWindowTitle("Validation Result")
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        style_path = os.path.join(current_dir, 'styles.qss')
        if os.path.exists(style_path):
            with open(style_path, 'r') as f:
                msg.setStyleSheet(f.read())
        
        msg.exec_()

    def closeEvent(self, event):
        """Ask for confirmation before closing so that a stray double-click
        on the taskbar / title-bar does not silently quit the app."""
        if self.bulk_thread and self.bulk_thread.isRunning():
            reply = QtWidgets.QMessageBox.question(
                self,
                "Verification in Progress",
                "Bulk verification is still running.\nAre you sure you want to quit?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if reply == QtWidgets.QMessageBox.No:
                event.ignore()
                return
            self.bulk_thread.stop()
            self.bulk_thread.wait()
        event.accept()
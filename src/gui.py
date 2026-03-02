import os
import csv
import concurrent.futures
import re
from PyQt5 import QtWidgets, QtCore, QtGui
from lib.validators import is_valid_email_syntax, has_mx_record, verify_email_smtp
import pandas as pd


def clean_smtp_message(message):
    """Clean SMTP message by removing enhanced status code prefixes like \n5.1.1"""
    if not message:
        return message
    # Handle escaped newlines (\n as two characters) first
    cleaned = message.replace('\\n5.1.1', ' ')
    cleaned = message.replace('\\n5.2.1', ' ')
    cleaned = cleaned.replace('\\n4.2.2', ' ')
    cleaned = cleaned.replace('\\n4.2.0', ' ')
    # Handle 5.1.1, 5.2.1 (mailbox does not exist)
    cleaned = cleaned.replace('\n5.1.1', ' ')
    cleaned = cleaned.replace('\n5.2.1', ' ')
    # Handle 4.2.0, 4.2.2 (mailbox over quota / out of storage)
    cleaned = cleaned.replace('\n4.2.2', ' ')
    cleaned = cleaned.replace('\n4.2.0', ' ')
    # Remove newlines followed by status code pattern (e.g., \n5.1.1, \n4.2.0)
    cleaned = re.sub(r'\n\d+\.\d+\.\d+\s*', ' ', cleaned)
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
        self.setMinimumSize(720, 480)
        
        # Set window flags: add maximize/minimize, remove help button
        self.setWindowFlags(
            QtCore.Qt.Window |
            QtCore.Qt.WindowMinimizeButtonHint |
            QtCore.Qt.WindowMaximizeButtonHint
        )
        
        self.layout = QtWidgets.QVBoxLayout()

        # Status bar: elapsed time + progress count
        self.status_label = QtWidgets.QLabel("⏱ 0:00:00  |  0 / 0 verified")
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        font = self.status_label.font()
        font.setBold(True)
        font.setPointSize(15)  # Increased by 10%
        self.status_label.setFont(font)
        self.layout.addWidget(self.status_label)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Email", "Status", "SMTP Message"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.table.setColumnWidth(0, 300)  # Make email column wider
        
        self.layout.addWidget(self.table)
        self.setLayout(self.layout)

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
        with concurrent.futures.ThreadPoolExecutor(max_workers=75) as executor:
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
        
        # Load custom fonts
        self.load_custom_fonts()
        
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

    def load_custom_fonts(self):
        """Load custom font from src/fonts directory."""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        fonts_dir = os.path.join(current_dir, 'fonts')
        
        # Font file - use FiraCode-Regular.ttf
        font_path = os.path.join(fonts_dir, 'FiraCode-Regular.ttf')
        
        font_database = QtGui.QFontDatabase()
        
        if os.path.exists(font_path):
            font_id = font_database.addApplicationFont(font_path)
            if font_id != -1:
                families = font_database.applicationFontFamilies(font_id)
                if families:
                    self._custom_font_family = families[0]
            else:
                self._custom_font_family = 'Consolas'
        else:
            self._custom_font_family = 'Consolas'
        
        # Set default font for the application
        default_font = QtGui.QFont(self._custom_font_family)
        default_font.setPointSize(11)  # Increased by 10%
        QtWidgets.QApplication.setFont(default_font)

    def init_ui(self):
        self.setWindowTitle("KnowEmail")
        self.setMinimumSize(720, 360)
        
        # Set window icon
        current_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(current_dir, '..', 'favicon.ico')
        self.setWindowIcon(QtGui.QIcon(icon_path))

        # Main layout
        main_layout = QtWidgets.QVBoxLayout()
        main_layout.setContentsMargins(48, 36, 48, 36)
        main_layout.setSpacing(18)

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
        description.setAlignment(QtCore.Qt.AlignHCenter)
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

        # Bulk Verify Button
        self.bulk_button = QtWidgets.QPushButton("Check Multiple Emails")
        self.bulk_button.setObjectName("bulkButton")
        self.bulk_button.clicked.connect(self.bulk_verify)
        main_layout.addWidget(self.bulk_button)

        self.setLayout(main_layout)

    def bulk_verify(self):
        file_dialog = QtWidgets.QFileDialog()
        file_path, _ = file_dialog.getOpenFileName(
            self,
            "Select Email List",
            "",
            "Text File (*.txt)"
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
            style_content = f.read()
        
        # Replace font-family in stylesheet with custom font
        custom_font = getattr(self, '_custom_font_family', 'Consolas')
        style_content = style_content.replace(
            "font-family: 'Segoe UI', Arial, sans-serif;",
            f"font-family: '{custom_font}', Consolas, monospace;"
        )
        
        self.setStyleSheet(style_content)

    def apply_styles_to_widget(self, widget):
        """Apply stylesheet with custom font to any widget (e.g., QMessageBox)."""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        style_path = os.path.join(current_dir, 'styles.qss')
        with open(style_path, 'r') as f:
            style_content = f.read()
        
        # Check for invalid properties
        # Replace font-family in stylesheet with custom font
        custom_font = getattr(self, '_custom_font_family', 'Consolas')
        style_content = style_content.replace(
            "font-family: 'Segoe UI', Arial, sans-serif;",
            f"font-family: '{custom_font}', Consolas, monospace;"
        )
        
        widget.setStyleSheet(style_content)

    def update_verifying_text(self):
        dots = '.' * self.verifying_counter
        self.validate_button.setText(f"Verifying{dots}")
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
        self.validate_button.setText("Verifying...")
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
        self.validate_button.setText("Check")
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
        self.validate_button.setText("Check")
    
        msg = QtWidgets.QMessageBox(self)
        msg.setIcon(QtWidgets.QMessageBox.Information)
        msg.setText(message)
        msg.setWindowTitle("Validation Result")
        
        # Apply stylesheet with custom font using the helper method
        self.apply_styles_to_widget(msg)
        
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
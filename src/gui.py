import os
import csv
import time
import threading
import webbrowser
import concurrent.futures
from PyQt5 import QtWidgets, QtCore, QtGui
from lib.validators import is_valid_email_syntax, has_mx_record, verify_email_smtp
import pandas as pd

class ResultDialog(QtWidgets.QDialog):
    def __init__(self, total_emails=0, parent=None):
        super().__init__(parent)
        self._total = total_emails
        self._processed = 0
        self._pause_callback = None
        self._update_window_title()
        self.setMinimumSize(700, 500)
        self._start_time = time.time()
        self._elapsed_timer = QtCore.QTimer(self)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
        self._elapsed_timer.start(500)

        self.layout = QtWidgets.QVBoxLayout()

        # --- Stats bar (line count + elapsed time) ---
        stats_layout = QtWidgets.QHBoxLayout()

        self._count_label = QtWidgets.QLabel(f"Processed: 0 / {self._total}")
        self._count_label.setObjectName("statsLabel")

        self._elapsed_label = QtWidgets.QLabel("Elapsed: 0s")
        self._elapsed_label.setObjectName("statsLabel")

        stats_layout.addWidget(self._count_label)
        stats_layout.addStretch(1)
        stats_layout.addWidget(self._elapsed_label)
        self.layout.addLayout(stats_layout)

        # --- Results table ---
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Email", "Status"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.layout.addWidget(self.table)

        # --- Action buttons: row 1 (Pause/Resume + Copy) ---
        btn_row1 = QtWidgets.QHBoxLayout()

        self._pause_btn = QtWidgets.QPushButton("Pause")
        self._pause_btn.setObjectName("pauseButton")
        self._pause_btn.setCheckable(True)
        self._pause_btn.clicked.connect(self._on_pause_toggle)

        self._copy_btn = QtWidgets.QPushButton("Copy to Clipboard")
        self._copy_btn.setObjectName("actionButton")
        self._copy_btn.clicked.connect(self.copy_to_clipboard)

        btn_row1.addWidget(self._pause_btn)
        btn_row1.addWidget(self._copy_btn)
        self.layout.addLayout(btn_row1)

        # --- Action buttons: row 2 (Export CSV + Export TXT) ---
        btn_row2 = QtWidgets.QHBoxLayout()

        self._export_csv_btn = QtWidgets.QPushButton("Export as CSV")
        self._export_csv_btn.setObjectName("actionButton")
        self._export_csv_btn.clicked.connect(lambda: self.export_results("csv"))

        self._export_txt_btn = QtWidgets.QPushButton("Export as TXT")
        self._export_txt_btn.setObjectName("actionButton")
        self._export_txt_btn.clicked.connect(lambda: self.export_results("txt"))

        btn_row2.addWidget(self._export_csv_btn)
        btn_row2.addWidget(self._export_txt_btn)
        self.layout.addLayout(btn_row2)

        self.setLayout(self.layout)

        # Enable the "?" help button
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowContextHelpButtonHint)

    # ------------------------------------------------------------------
    # Window title helper
    # ------------------------------------------------------------------
    def _update_window_title(self):
        self.setWindowTitle(f"Verifying {self._processed} / {self._total} emails...")

    # ------------------------------------------------------------------
    # Public read-only properties
    # ------------------------------------------------------------------
    @property
    def processed(self):
        return self._processed

    @property
    def total(self):
        return self._total

    # ------------------------------------------------------------------
    # Timer helpers
    # ------------------------------------------------------------------
    def _update_elapsed(self):
        elapsed = int(time.time() - self._start_time)
        self._elapsed_label.setText(f"Elapsed: {elapsed}s")

    def stop_timer(self):
        """Call this when verification is complete."""
        self._elapsed_timer.stop()
        elapsed = int(time.time() - self._start_time)
        self._elapsed_label.setText(f"Elapsed: {elapsed}s (done)")
        # Disable pause button once done
        self._pause_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Pause / Resume
    # ------------------------------------------------------------------
    def _on_pause_toggle(self, checked: bool):
        self._pause_btn.setText("Resume" if checked else "Pause")
        # Notify the thread via the callback set by EmailValidatorApp
        if self._pause_callback:
            self._pause_callback(checked)

    def set_pause_callback(self, callback):
        """Register a callable(paused: bool) that the dialog calls on toggle."""
        self._pause_callback = callback

    # ------------------------------------------------------------------
    # Row management
    # ------------------------------------------------------------------
    def add_row(self, email, status):
        row_position = self.table.rowCount()
        self.table.insertRow(row_position)

        email_item = QtWidgets.QTableWidgetItem(email)
        status_item = QtWidgets.QTableWidgetItem(status)

        if status == "Valid":
            status_item.setForeground(QtGui.QColor('#27ae60'))  # Green
        elif status.startswith("Invalid"):
            status_item.setForeground(QtGui.QColor('#e74c3c'))  # Red
        else:
            status_item.setForeground(QtGui.QColor('#f1c40f'))  # Yellow

        self.table.setItem(row_position, 0, email_item)
        self.table.setItem(row_position, 1, status_item)

        # Update count label and window title
        self._processed = self.table.rowCount()
        self._count_label.setText(f"Processed: {self._processed} / {self._total}")
        self._update_window_title()

    # ------------------------------------------------------------------
    # Export helpers
    # ------------------------------------------------------------------
    def _get_table_data(self):
        """Return list of (email, status) tuples from the table."""
        rows = []
        for r in range(self.table.rowCount()):
            email = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
            status = self.table.item(r, 1).text() if self.table.item(r, 1) else ""
            rows.append((email, status))
        return rows

    def copy_to_clipboard(self):
        """Copy all results to the system clipboard as tab-delimited text."""
        rows = self._get_table_data()
        if not rows:
            QtWidgets.QMessageBox.information(self, "Copy", "No results to copy.")
            return

        lines = ["Email\tStatus"]
        for email, status in rows:
            lines.append(f"{email}\t{status}")

        text = "\n".join(lines)
        QtWidgets.QApplication.clipboard().setText(text)
        QtWidgets.QMessageBox.information(
            self, "Copied", f"{len(rows)} result(s) copied to clipboard."
        )

    def export_results(self, fmt: str):
        """Export results to a tab-delimited CSV or TXT file."""
        rows = self._get_table_data()
        if not rows:
            QtWidgets.QMessageBox.information(self, "Export", "No results to export.")
            return

        if fmt == "csv":
            file_filter = "CSV File (*.csv)"
            default_ext = ".csv"
        else:
            file_filter = "Text File (*.txt)"
            default_ext = ".txt"

        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Results",
            f"email_results{default_ext}",
            file_filter,
        )

        if not file_path:
            return

        try:
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                if fmt == "csv":
                    writer = csv.writer(f)
                else:
                    writer = csv.writer(f, delimiter="\t")
                writer.writerow(["Email", "Status"])
                writer.writerows(rows)

            QtWidgets.QMessageBox.information(
                self, "Export Complete", f"Results saved to:\n{file_path}"
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Export Error", f"Failed to save file:\n{str(e)}"
            )

    # ------------------------------------------------------------------
    # Help button
    # ------------------------------------------------------------------
    def showEvent(self, event):
        """Override showEvent to ensure the help button is available."""
        super().showEvent(event)

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
        help_dialog.setTextFormat(QtCore.Qt.RichText)
        help_dialog.setText(help_text)
        help_dialog.setStandardButtons(QtWidgets.QMessageBox.Ok)
        help_dialog.exec_()


class SingleVerificationWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal(str, bool)

    def __init__(self, email):
        super().__init__()
        self.email = email

    def run(self):
        try:
            if not is_valid_email_syntax(self.email):
                self.finished.emit("Invalid email syntax", False)
                return

            domain = self.email.split('@')[1]
            if not has_mx_record(domain):
                self.finished.emit("Domain does not have MX records", False)
                return

            if not verify_email_smtp(self.email):
                self.finished.emit("SMTP verification failed! Email is not valid.", False)
            else:
                self.finished.emit("Email is valid and appears to be reachable", True)
        except Exception as e:
            self.finished.emit(f"Error: {str(e)}", False)

class BulkVerificationThread(QtCore.QThread):
    result_signal = QtCore.pyqtSignal(str, str)
    all_done = QtCore.pyqtSignal()

    def __init__(self, emails):
        super().__init__()
        self.emails = emails
        self.is_running = True
        self._pause_event = threading.Event()
        self._pause_event.set()  # not paused initially

    def run(self):
        emails = [e for e in self.emails if e]
        batch_size = 100

        for i in range(0, len(emails), batch_size):
            # Block before submitting each batch so no new network calls
            # are made while paused.
            self._pause_event.wait()
            if not self.is_running:
                break

            batch = emails[i:i + batch_size]
            with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
                future_to_email = {
                    executor.submit(self.verify_single_email, email): email
                    for email in batch
                }

                for future in concurrent.futures.as_completed(future_to_email):
                    # Block result collection while paused
                    self._pause_event.wait()

                    if not self.is_running:
                        executor.shutdown(wait=False, cancel_futures=True)
                        break

                    email = future_to_email[future]
                    try:
                        status = future.result()
                    except Exception as e:
                        status = f"Error: {str(e)}"

                    self.result_signal.emit(email, status)

                if not self.is_running:
                    break

        if self.is_running:
            self.all_done.emit()

    def verify_single_email(self, email):
        # Block here while paused so no new network calls are made
        self._pause_event.wait()
        try:
            if not is_valid_email_syntax(email):
                return "Invalid (Syntax)"

            domain = email.split('@')[1]
            if not has_mx_record(domain):
                return "Invalid (No MX)"

            if not verify_email_smtp(email):
                return "Invalid (SMTP)"

            return "Valid"
        except Exception as e:
            return f"Error: {str(e)}"

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def stop(self):
        self.is_running = False
        self._pause_event.set()  # unblock if paused so the thread can exit

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

    def init_ui(self):
        self.setWindowTitle("KnowEmail")
        self.setMinimumSize(600, 500)

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
            
        # Stop any previous run BEFORE reassigning self.results_dialog so that
        # stale result_signal emissions from the old thread cannot land in the
        # new dialog (update_results uses self.results_dialog by reference).
        if self.bulk_thread and self.bulk_thread.isRunning():
            self.bulk_thread.stop()
            self.bulk_thread.wait()

        self.results_dialog = ResultDialog(total_emails=len(emails), parent=self)
        self.results_dialog.show()

        self.bulk_thread = BulkVerificationThread(emails)
        self.bulk_thread.result_signal.connect(self.update_results)
        self.bulk_thread.all_done.connect(self.on_bulk_done)

        # Wire the pause/resume button in the dialog to the thread
        self.results_dialog.set_pause_callback(self._on_pause_requested)

        self.bulk_thread.start()

    def _on_pause_requested(self, paused: bool):
        """Called by ResultDialog when the Pause/Resume button is toggled."""
        if self.bulk_thread and self.bulk_thread.isRunning():
            if paused:
                self.bulk_thread.pause()
            else:
                self.bulk_thread.resume()

    def on_bulk_done(self):
        """Called when all bulk verification is complete."""
        if hasattr(self, 'results_dialog') and self.results_dialog:
            self.results_dialog.stop_timer()
            self.results_dialog.setWindowTitle(
                f"Done — {self.results_dialog.processed} / {self.results_dialog.total} emails verified"
            )
        self.show_completion_popup()

    def show_completion_popup(self):
        QtWidgets.QMessageBox.information(
            self,
            "Process Complete",
            "All emails from the file have been checked!",
            QtWidgets.QMessageBox.Ok
        )

    def update_results(self, email, status):
        if hasattr(self, 'results_dialog') and self.results_dialog:
            self.results_dialog.add_row(email, status)

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

    def handle_single_verification_result(self, message, is_valid):
        self.verifying_timer.stop()
        self.result_label.setText("")
        self.validate_button.setEnabled(True)
        self.email_input.setEnabled(True)
        
        self.show_popup(message)

    def show_popup(self, message):
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

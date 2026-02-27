import os
import csv
import json
import datetime
import threading
import webbrowser
from PyQt5 import QtWidgets, QtCore, QtGui
from lib.validators import is_valid_email_syntax, has_mx_record, verify_email_smtp
import pandas as pd

# Path to the pause/resume cache file (stored next to main.py at project root)
_CACHE_FILE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'knowemail_pause_cache.json')
)


_CACHE_MAX_AGE_DAYS = 7  # Discard pause caches older than this many days


def _load_cache_safe(cache_file):
    """Load the pause cache JSON file; return None on any error."""
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _is_cache_stale(cache: dict) -> bool:
    """Return True if the cache's created_at timestamp is older than _CACHE_MAX_AGE_DAYS."""
    created_at_str = cache.get("created_at")
    if not created_at_str:
        return False  # old cache without timestamp — treat as fresh to avoid breaking existing sessions
    try:
        created_at = datetime.datetime.fromisoformat(created_at_str)
        age = datetime.datetime.utcnow() - created_at
        return age.days >= _CACHE_MAX_AGE_DAYS
    except (ValueError, TypeError):
        return False


class ResultDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KnowEmail - Verifying Bulk Emails")
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
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Email", "Status"])
        self.table.horizontalHeader().setStretchLastSection(True)
        
        self.layout.addWidget(self.table)

        # Pause / Resume button
        self.pause_resume_button = QtWidgets.QPushButton("⏸ Pause")
        self.pause_resume_button.setObjectName("pauseResumeButton")
        self.layout.addWidget(self.pause_resume_button)

        self.setLayout(self.layout)

        # Enable the "?" help button
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowContextHelpButtonHint)


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

    def update_status(self, elapsed_str, done, total):
        self.status_label.setText(f"⏱ {elapsed_str}  |  {done} / {total} verified")

    def set_paused_state(self, paused: bool):
        """Update the button label to reflect paused/running state."""
        if paused:
            self.pause_resume_button.setText("▶ Resume")
        else:
            self.pause_resume_button.setText("⏸ Pause")
    
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

import concurrent.futures

class SingleVerificationWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal(str, bool)

    def __init__(self, email):
        super().__init__()
        self.email = email

    def run(self):
        try:
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
    # Emitted when the thread pauses; carries the list of emails not yet submitted
    paused_signal = QtCore.pyqtSignal(list)
    
    def __init__(self, emails):
        super().__init__()
        self.emails = list(emails)
        self.is_running = True
        self._pause_event = threading.Event()
        
    def run(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
            futures = {}

            # Submit emails one-by-one so we can detect a pause request between submissions
            for idx, email in enumerate(self.emails):
                if not email:
                    continue

                # Check for stop
                if not self.is_running:
                    executor.shutdown(wait=False, cancel_futures=True)
                    return

                # Check for pause — wait for in-flight futures, then signal remaining emails
                if self._pause_event.is_set():
                    # Wait for already-submitted futures to complete
                    for future, em in list(futures.items()):
                        try:
                            status = future.result()
                        except Exception as e:
                            status = f"Error: {str(e)}"
                        self.result_signal.emit(em, status)
                    futures.clear()

                    # Remaining emails are those not yet submitted
                    remaining = [e for e in self.emails[idx:] if e]
                    self.paused_signal.emit(remaining)
                    return

                future = executor.submit(self.verify_single_email, email)
                futures[future] = email

            # All emails submitted — collect remaining results one at a time
            # (do NOT wrap in list() — that would block until all are done and
            #  prevent the pause check from ever triggering mid-collection)
            pending_futures = set(futures.keys())
            for future in concurrent.futures.as_completed(futures):
                if not self.is_running:
                    executor.shutdown(wait=False, cancel_futures=True)
                    return

                pending_futures.discard(future)

                # Check for pause during final result collection
                if self._pause_event.is_set():
                    # Emit the result for this just-completed future
                    em = futures[future]
                    try:
                        status = future.result()
                    except Exception as e:
                        status = f"Error: {str(e)}"
                    self.result_signal.emit(em, status)

                    # Any futures still pending haven't completed yet — re-verify on resume
                    still_remaining = [futures[f] for f in pending_futures]
                    self.paused_signal.emit(still_remaining)
                    return

                email = futures[future]
                try:
                    status = future.result()
                except Exception as e:
                    status = f"Error: {str(e)}"

                self.result_signal.emit(email, status)
                
        if self.is_running:
            self.all_done.emit()

    def verify_single_email(self, email):
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

    def stop(self):
        self.is_running = False

    def pause(self):
        """Request the thread to pause after the current in-flight batch finishes."""
        self._pause_event.set()

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

        # Pause/resume state
        self._is_paused = False
        self._cache_file = os.path.normpath(_CACHE_FILE)

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

    # ------------------------------------------------------------------
    # Pause / Resume helpers
    # ------------------------------------------------------------------

    def _save_pause_cache(self, remaining_emails):
        """Write the pause cache file with remaining emails and verified results so far."""
        data = {
            "remaining_emails": remaining_emails,
            "verified_results": self._bulk_results,
            "elapsed_seconds": self._elapsed_seconds,
            "total_emails": self._total_emails,
            "created_at": datetime.datetime.utcnow().isoformat(),
        }
        try:
            with open(self._cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "Cache Error", f"Could not save pause cache:\n{str(e)}"
            )

    def _delete_pause_cache(self):
        """Remove the pause cache file if it exists."""
        try:
            if os.path.exists(self._cache_file):
                os.remove(self._cache_file)
        except Exception:
            pass

    def _on_thread_paused(self, remaining_emails):
        """Slot called when BulkVerificationThread emits paused_signal."""
        self._elapsed_timer.stop()
        self._save_pause_cache(remaining_emails)
        self._is_paused = True
        if getattr(self, 'results_dialog', None) and self.results_dialog.isVisible():
            self.results_dialog.set_paused_state(True)

    def _toggle_pause_resume(self):
        """Called when the Pause/Resume button in ResultDialog is clicked."""
        if self._is_paused:
            self._resume_bulk()
        else:
            self._pause_bulk()

    def _pause_bulk(self):
        """Request the running bulk thread to pause."""
        if self.bulk_thread and self.bulk_thread.isRunning():
            self.bulk_thread.pause()
            # UI update happens in _on_thread_paused once the thread actually pauses

    def _resume_bulk(self):
        """Resume a paused bulk verification from the cache file."""
        cache = _load_cache_safe(self._cache_file)
        if not cache:
            QtWidgets.QMessageBox.warning(self, "Resume Error", "No pause cache found.")
            return

        remaining = cache.get("remaining_emails", [])
        if not remaining:
            # Nothing left to verify — treat as done
            self._is_paused = False
            if getattr(self, 'results_dialog', None):
                self.results_dialog.set_paused_state(False)
            self.on_bulk_all_done()
            return

        # Restore state (including verified results so a subsequent pause saves them correctly)
        self._bulk_results = list(cache.get("verified_results", []))
        # Clear the table before repopulating to avoid duplicate rows if the same
        # dialog instance is still open from before the pause.
        self.results_dialog.table.setRowCount(0)
        for email, status in self._bulk_results:
            self.results_dialog.add_row(email, status)
        self._verified_count = len(self._bulk_results)
        self._elapsed_seconds = cache.get("elapsed_seconds", self._elapsed_seconds)
        self._total_emails = cache.get("total_emails", self._total_emails)
        self._is_paused = False

        if getattr(self, 'results_dialog', None) and self.results_dialog.isVisible():
            self.results_dialog.set_paused_state(False)

        # Start a new thread for the remaining emails
        self.bulk_thread = BulkVerificationThread(remaining)
        self.bulk_thread.result_signal.connect(self.update_results)
        self.bulk_thread.all_done.connect(self.on_bulk_all_done)
        self.bulk_thread.paused_signal.connect(self._on_thread_paused)
        self.bulk_thread.start()

        self._elapsed_timer.start(1000)

    # ------------------------------------------------------------------
    # Bulk verification
    # ------------------------------------------------------------------

    def bulk_verify(self):
        # If a pause cache exists, offer to resume it (unless it is stale)
        if os.path.exists(self._cache_file):
            cache = _load_cache_safe(self._cache_file)
            if cache and _is_cache_stale(cache):
                # Cache is too old — silently discard it and start fresh
                self._delete_pause_cache()
            elif cache:
                reply = QtWidgets.QMessageBox.question(
                    self,
                    "Resume Paused Session?",
                    "A paused verification session was found.\n\n"
                    "Would you like to resume it, or start a fresh verification?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.Yes,
                )
                if reply == QtWidgets.QMessageBox.Yes:
                    self._restore_and_resume()
                    return
                else:
                    self._delete_pause_cache()

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
                with open(file_path, 'r', encoding='utf-8') as f:
                    emails = [line.strip() for line in f.readlines() if line.strip()]
            elif file_path.endswith('.xlsx'):
                df = pd.read_excel(file_path)
                emails = df.iloc[:, 0].astype(str).tolist()
            else:
                raise ValueError("Unsupported file format")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to read file: {str(e)}")
            return
            
        self._start_bulk_session(emails)

    def _restore_and_resume(self):
        """Restore a paused session from cache and open the ResultDialog."""
        cache = _load_cache_safe(self._cache_file)
        if not cache:
            QtWidgets.QMessageBox.warning(self, "Resume Error", "Could not read the pause cache.")
            return

        verified_results = cache.get("verified_results", [])
        remaining = cache.get("remaining_emails", [])
        elapsed = cache.get("elapsed_seconds", 0)
        total = cache.get("total_emails", len(verified_results) + len(remaining))

        # Disconnect old dialog if present
        if hasattr(self, 'results_dialog'):
            try:
                self.results_dialog.finished.disconnect(self._elapsed_timer.stop)
            except TypeError:
                pass

        self.results_dialog = ResultDialog(self)
        self.results_dialog.finished.connect(self._elapsed_timer.stop)
        self.results_dialog.pause_resume_button.clicked.connect(self._toggle_pause_resume)
        self.results_dialog.show()

        # Restore already-verified results into the dialog
        self._bulk_results = []
        for email, status in verified_results:
            self._bulk_results.append((email, status))
            self.results_dialog.add_row(email, status)

        self._total_emails = total
        self._verified_count = len(verified_results)
        self._elapsed_seconds = elapsed
        self._is_paused = False

        if not remaining:
            self.on_bulk_all_done()
            return

        self._elapsed_timer.start(1000)

        self.bulk_thread = BulkVerificationThread(remaining)
        self.bulk_thread.result_signal.connect(self.update_results)
        self.bulk_thread.all_done.connect(self.on_bulk_all_done)
        self.bulk_thread.paused_signal.connect(self._on_thread_paused)
        self.bulk_thread.start()

    def _start_bulk_session(self, emails):
        """Start a fresh bulk verification session with the given email list."""
        if hasattr(self, 'results_dialog'):
            try:
                self.results_dialog.finished.disconnect(self._elapsed_timer.stop)
            except TypeError:
                pass

        self.results_dialog = ResultDialog(self)
        self.results_dialog.finished.connect(self._elapsed_timer.stop)
        self.results_dialog.pause_resume_button.clicked.connect(self._toggle_pause_resume)
        self.results_dialog.show()
        self._bulk_results = []

        # Stop any running thread
        if self.bulk_thread and self.bulk_thread.isRunning():
            self.bulk_thread.stop()
            self.bulk_thread.wait()

        self._total_emails = len(emails)
        self._verified_count = 0
        self._elapsed_seconds = 0
        self._is_paused = False
        self._elapsed_timer.start(1000)

        self.bulk_thread = BulkVerificationThread(emails)
        self.bulk_thread.result_signal.connect(self.update_results)
        self.bulk_thread.all_done.connect(self.on_bulk_all_done)
        self.bulk_thread.paused_signal.connect(self._on_thread_paused)
        self.bulk_thread.start()

    def on_bulk_all_done(self):
        self._elapsed_timer.stop()
        # Clean up the pause cache on successful completion
        self._delete_pause_cache()
        self._is_paused = False
        if getattr(self, 'results_dialog', None) and self.results_dialog.isVisible():
            self.results_dialog.set_paused_state(False)
            self.results_dialog.pause_resume_button.setEnabled(False)

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
                writer.writerow(["Email", "Status"])
                writer.writerows(self._bulk_results)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Export Error", f"Failed to save CSV: {str(e)}")

    def update_results(self, email, status):
        self._bulk_results.append((email, status))
        self.results_dialog.add_row(email, status)
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

    def handle_single_verification_result(self, message, is_valid):
        self.verifying_timer.stop()
        self.result_label.setText("")
        self.validate_button.setEnabled(True)
        self.email_input.setEnabled(True)
        
        self.show_popup(message)

    def verify_in_background(self, email):
        # Deprecated: Logic moved to SingleVerificationWorker
        pass

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



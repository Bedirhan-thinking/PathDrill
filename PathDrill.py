import os
import json
import sys
import csv
import base64
from datetime import datetime

# GitHub standards and professional Python packaging
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QTreeView, QFileSystemModel, QSpinBox, 
                             QLabel, QPushButton, QMessageBox, QCheckBox,
                             QSplitter, QTextEdit, QProgressBar, QHeaderView, QLineEdit, QGroupBox, QComboBox)
from PySide6.QtCore import Qt, QDir, QThread, Signal, QItemSelectionModel
from PySide6.QtGui import QIcon, QPixmap

# Increase recursion depth for deeply nested directory structures
sys.setrecursionlimit(1000000)

PATHDRILL_LOGO_DATA = """
"""

def format_size(size_bytes):
    """Converts bytes to a human-readable format."""
    if size_bytes == 0: return "0 B"
    units = ("B", "KB", "MB", "GB", "TB")
    i = 0
    while size_bytes >= 1024 and i < len(units) - 1:
        size_bytes /= 1024
        i += 1
    return f"{size_bytes:.2f} {units[i]}"

class ScanEngine(QThread):
    progress_signal = Signal(int)       # 0 to 100 percentage
    phase_signal = Signal(str)          # To update UI regarding Phase 1 vs Phase 2
    heartbeat_signal = Signal(str)      # Sub-status updates
    log_signal = Signal(str)
    finished_signal = Signal(dict)

    def __init__(self, target_paths, max_depth, save_path, options):
        super().__init__()
        self.target_paths = target_paths
        self.max_depth = max_depth
        self.save_path = save_path
        self.options = options
        self._is_cancelled = False
        
        # Architecture Counters
        self.total_expected_nodes = 0
        self.total_nodes_scanned = 0
        self.unreadable_nodes = 0

    def cancel(self):
        """Safely signals the thread to terminate its operations."""
        self._is_cancelled = True
        self.log_signal.emit("\n[!] ABORT SIGNAL RECEIVED. Commencing graceful shutdown...")

    def _fast_count_nodes(self, current_path, current_depth):
        """
        Phase 1 Algorithm: Lightning fast topological counting without metadata extraction.
        Respects the exact depth limitations of the main algorithm.
        """
        if self._is_cancelled: return 0
        
        count = 1 # Count the current directory/file itself
        
        # Periodic heartbeat for massive Phase 1 scans
        if count % 50000 == 0:
            self.heartbeat_signal.emit(f"Phase 1: Indexing topology... (Discovered so far: {self.total_expected_nodes + count:,})")

        if os.path.isdir(current_path):
            if self.max_depth != -1 and current_depth >= self.max_depth:
                return count # Hit depth wall, return count as is

            try:
                # os.scandir is an iterator yielding DirEntry objects. Much faster than os.listdir.
                with os.scandir(current_path) as scanner:
                    for item in scanner:
                        count += self._fast_count_nodes(item.path, current_depth + 1)
            except (PermissionError, OSError):
                pass # Unreadable nodes are handled in Phase 2 for error logging
                
        return count

    def build_tree(self, current_path, current_depth):
        """
        Phase 2 Algorithm: Full Metadata Extraction (Deep Scanning).
        """
        if self._is_cancelled:
            return {"name": os.path.basename(current_path) or current_path, "error": "Aborted"}

        self.total_nodes_scanned += 1
        
        # Calculate Deterministic Percentage
        if self.total_expected_nodes > 0:
            percentage = int((self.total_nodes_scanned / self.total_expected_nodes) * 100)
            
            # Emit progress sparingly to not throttle the UI thread (every 1000 items or 1%)
            if self.total_nodes_scanned % 1000 == 0:
                self.progress_signal.emit(percentage)
                self.heartbeat_signal.emit(f"Phase 2: Extracting... {percentage}% ({self.total_nodes_scanned:,} / {self.total_expected_nodes:,})")

        name = os.path.basename(current_path)
        node = {"name": name if name else current_path}
        
        if self.options.get("include_path", True):
            node["full_path"] = os.path.normpath(current_path)
        
        try:
            # This is the heavy I/O part. Benefiting heavily from Phase 1 OS Cache.
            stats = os.stat(current_path)
            if self.options.get("include_date", True):
                node["last_modified"] = datetime.fromtimestamp(stats.st_mtime).isoformat()
            if self.options.get("include_bytes", True):
                node["size_bytes"] = stats.st_size
            if self.options.get("include_readable", True):
                node["size_readable"] = format_size(stats.st_size)
        except OSError:
            self.unreadable_nodes += 1
            node["error"] = "Metadata unreadable (Permission/Lock)"
            return node

        if os.path.isdir(current_path):
            node["type"] = "directory"
            if self.max_depth != -1 and current_depth >= self.max_depth:
                return node

            node["contents"] = []
            try:
                with os.scandir(current_path) as scanner:
                    for item in scanner:
                        if self._is_cancelled: break
                        node["contents"].append(self.build_tree(item.path, current_depth + 1))
            except PermissionError:
                self.unreadable_nodes += 1
                node["error"] = "Access Denied"
        else:
            node["type"] = "file"
            if self.options.get("include_extension", True):
                node["extension"] = os.path.splitext(current_path)[1].lower()

        return node

    # --- EXPORT STRATEGIES ---
    def export_to_json(self, data, file_path):
        minify = self.options.get("minify_output", False)
        indent_level = None if minify else 4 
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent_level, ensure_ascii=False)

    def export_to_csv(self, data, file_path):
        rows = []
        def flatten(nodes):
            for node in nodes:
                row = {
                    "Name": node.get("name", ""),
                    "Type": node.get("type", ""),
                    "Full Path": node.get("full_path", ""),
                    "Size (Bytes)": node.get("size_bytes", ""),
                    "Size (Readable)": node.get("size_readable", ""),
                    "Last Modified": node.get("last_modified", ""),
                    "Extension": node.get("extension", ""),
                    "Error": node.get("error", "")
                }
                rows.append(row)
                if "contents" in node: flatten(node["contents"])
        
        flatten(data["scan_results"])
        with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
            fieldnames = ["Name", "Type", "Full Path", "Size (Bytes)", "Size (Readable)", "Last Modified", "Extension", "Error"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def export_to_txt(self, data, file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"PathDrill Report - Generated at {data['report_info']['creation_datetime']}\n")
            f.write("=" * 60 + "\n\n")
            def write_tree(nodes, prefix=""):
                for i, node in enumerate(nodes):
                    is_last = (i == len(nodes) - 1)
                    connector = "└── " if is_last else "├── "
                    size_info = f" ({node.get('size_readable', '')})" if 'size_readable' in node else ""
                    f.write(f"{prefix}{connector}{node.get('name', '')}{size_info}\n")
                    if "contents" in node:
                        extension = "    " if is_last else "│   "
                        write_tree(node["contents"], prefix + extension)
            write_tree(data["scan_results"])

    def export_to_md(self, data, file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# PathDrill Extraction Report\n")
            f.write(f"**Generated:** `{data['report_info']['creation_datetime']}`\n\n")
            def write_md(nodes, depth=0):
                indent = "  " * depth
                for node in nodes:
                    icon = "📁" if node.get("type") == "directory" else "📄"
                    name = f"**{node.get('name', '')}**" if node.get("type") == "directory" else node.get('name', '')
                    size_info = f" *({node.get('size_readable', '')})*" if 'size_readable' in node else ""
                    f.write(f"{indent}- {icon} {name}{size_info}\n")
                    if "contents" in node: write_md(node["contents"], depth + 1)
            write_md(data["scan_results"])

    def run(self):
        start_time = datetime.now()
        hierarchy_list = []
        
        self.log_signal.emit(f"### PathDrill OFFICIAL Scan Started: {start_time.strftime('%H:%M:%S')} ###")
        
        # ==========================================
        # PHASE 1: PRE-FLIGHT TOPOLOGY INDEXING
        # ==========================================
        self.phase_signal.emit("INDETERMINATE") # Tell UI to show spinner
        self.log_signal.emit("Phase 1: Initiating High-Speed Topological Indexing...")
        
        for path in self.target_paths:
            if self._is_cancelled: break
            if not os.path.exists(path): continue
            
            self.total_expected_nodes += self._fast_count_nodes(path, 0)
            
        if self._is_cancelled:
            self.wrap_up_and_exit(start_time, [])
            return

        self.log_signal.emit(f"Phase 1 Complete. Target structural size: {self.total_expected_nodes:,} nodes.")
        
        # ==========================================
        # PHASE 2: METADATA EXTRACTION (DFS)
        # ==========================================
        self.phase_signal.emit("DETERMINATE") # Tell UI to activate 0-100 progress bar
        self.log_signal.emit("Phase 2: Extracting deep metadata structures...")

        for path in self.target_paths:
            if self._is_cancelled: break
            if not os.path.exists(path): continue
            
            self.log_signal.emit(f"Anchoring at root: {path}")
            hierarchy_list.append(self.build_tree(path, 0))

        self.wrap_up_and_exit(start_time, hierarchy_list)

    def wrap_up_and_exit(self, start_time, hierarchy_list):
        """Helper function to compile and export data at the end of the thread."""
        status_message = "Aborted by User" if self._is_cancelled else "Completed Successfully"

        final_data = {
            "report_info": {
                "tool": "PathDrill-Extractor",
                "creation_datetime": start_time.isoformat(),
                "scanned_paths_count": len(self.target_paths),
                "total_nodes_extracted": self.total_nodes_scanned,
                "unreadable_nodes_count": self.unreadable_nodes,
                "defined_depth": self.max_depth if self.max_depth != -1 else "Unlimited",
                "metadata_filtering": self.options,
                "status": status_message
            },
            "scan_results": hierarchy_list
        }

        export_format = self.options.get("export_format", "JSON")
        
        try:
            self.log_signal.emit(f"Aggregating data... Formatting as {export_format}.")
            if export_format == "JSON":
                self.export_to_json(final_data, self.save_path)
            elif export_format == "CSV":
                self.export_to_csv(final_data, self.save_path)
            elif export_format == "TXT":
                self.export_to_txt(final_data, self.save_path)
            elif export_format == "MD":
                self.export_to_md(final_data, self.save_path)
            
            elapsed_time = datetime.now() - start_time
            
            if self._is_cancelled:
                self.log_signal.emit(f"### OPERATION ABORTED after {elapsed_time.total_seconds():.3f} seconds. ###")
                self.log_signal.emit(f"Partial report saved safely: {self.save_path}")
            else:
                self.log_signal.emit(f"### Completed in {elapsed_time.total_seconds():.3f} seconds. ###")
                self.log_signal.emit(f"Total Nodes: {self.total_nodes_scanned:,} | Errors/Locks: {self.unreadable_nodes:,}")
                self.log_signal.emit(f"Official report saved: {self.save_path}")
                
            self.progress_signal.emit(100) # Ensure bar is maxed out
            self.finished_signal.emit(final_data)
            
        except Exception as e:
            self.log_signal.emit(f"[!] Export Error: {str(e)}")
            self.finished_signal.emit({"error": str(e)})


class PathDrillApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PathDrill - Advanced Path Extraction & Ad-hoc Analysis Tool")
        self.resize(1150, 780)

        qpixmap = QPixmap()
        if PATHDRILL_LOGO_DATA.strip():
            qpixmap.loadFromData(base64.b64decode(PATHDRILL_LOGO_DATA))
        self.logo_icon = QIcon(qpixmap)
        self.setWindowIcon(self.logo_icon)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # --- LEFT SIDE: Explorer & Quick Nav ---
        file_manager_widget = QWidget()
        file_layout = QVBoxLayout(file_manager_widget)
        
        nav_layout = QHBoxLayout()
        logo_label = QLabel()
        if not qpixmap.isNull():
            logo_label.setPixmap(qpixmap.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        nav_layout.addWidget(logo_label)

        self.txt_search_path = QLineEdit()
        self.txt_search_path.setPlaceholderText("Paste full path or start typing...")
        self.txt_search_path.returnPressed.connect(self.go_to_path)
        self.txt_search_path.textChanged.connect(self.search_directories)
        nav_layout.addWidget(self.txt_search_path)
        
        self.btn_search = QPushButton("Find")
        self.btn_search.clicked.connect(self.search_directories)
        nav_layout.addWidget(self.btn_search)
        
        file_layout.addLayout(nav_layout)

        self.model = QFileSystemModel()
        self.model.setRootPath("") 
        self.model.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot | QDir.Hidden)
        
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setAnimated(True)
        self.tree.setIndentation(20)
        self.tree.setSortingEnabled(True)
        self.tree.setSelectionMode(QTreeView.ExtendedSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.doubleClicked.connect(self.on_item_double_clicked)
        
        initial_index = self.model.index(os.getcwd())
        self.tree.scrollTo(initial_index)
        self.tree.resizeColumnToContents(0)

        file_layout.addWidget(self.tree)
        splitter.addWidget(file_manager_widget)

        # --- RIGHT SIDE: Controls & Logs ---
        controls_panel = QWidget()
        controls_layout = QVBoxLayout(controls_panel)
        controls_layout.setContentsMargins(10, 0, 0, 0)
        
        banner_label = QLabel()
        if not qpixmap.isNull():
            banner_label.setPixmap(qpixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        banner_label.setAlignment(Qt.AlignCenter)
        controls_layout.addWidget(banner_label)
        
        # Options Group
        self.grp_options = QGroupBox("Metadata Extraction Parameters")
        options_layout = QVBoxLayout(self.grp_options)
        
        h_box_1 = QHBoxLayout()
        self.chk_include_path = QCheckBox("Absolute Path")
        self.chk_include_path.setChecked(True)
        self.chk_include_date = QCheckBox("Modified Date")
        self.chk_include_date.setChecked(True)
        h_box_1.addWidget(self.chk_include_path)
        h_box_1.addWidget(self.chk_include_date)
        options_layout.addLayout(h_box_1)

        h_box_2 = QHBoxLayout()
        self.chk_include_bytes = QCheckBox("Raw Size (B)")
        self.chk_include_bytes.setChecked(True)
        self.chk_include_readable = QCheckBox("Readable Size")
        self.chk_include_readable.setChecked(True)
        h_box_2.addWidget(self.chk_include_bytes)
        h_box_2.addWidget(self.chk_include_readable)
        options_layout.addLayout(h_box_2)
        
        h_box_3 = QHBoxLayout()
        self.chk_include_extension = QCheckBox("File Extension")
        self.chk_include_extension.setChecked(True)
        self.chk_minify = QCheckBox("Minify Output (Reduce File Size)")
        self.chk_minify.setToolTip("Removes formatting spaces. Crucial for massive entire-drive scans.")
        h_box_3.addWidget(self.chk_include_extension)
        h_box_3.addWidget(self.chk_minify)
        options_layout.addLayout(h_box_3)

        controls_layout.addWidget(self.grp_options)

        scan_grp = QGroupBox("Core Scan Controls")
        scan_layout = QVBoxLayout(scan_grp)
        
        format_layout = QHBoxLayout()
        lbl_format = QLabel("Export Format:")
        self.cmb_format = QComboBox()
        self.cmb_format.addItems(["JSON", "CSV", "TXT", "MD"])
        self.cmb_format.currentTextChanged.connect(self.update_output_extension)
        format_layout.addWidget(lbl_format)
        format_layout.addWidget(self.cmb_format)
        scan_layout.addLayout(format_layout)

        depth_layout = QHBoxLayout()
        lbl_depth = QLabel("Recursive Branching Depth:")
        lbl_depth.setToolTip("-1 Unlimited, 0 Root folders only.")
        self.spin_depth = QSpinBox()
        self.spin_depth.setRange(-1, 100)
        self.spin_depth.setValue(-1)
        depth_layout.addWidget(lbl_depth)
        depth_layout.addWidget(self.spin_depth)
        scan_layout.addLayout(depth_layout)

        output_layout = QHBoxLayout()
        lbl_output = QLabel("Output File Name:")
        self.txt_output_name = QTextEdit()
        self.txt_output_name.setPlainText("pathdrill_report.json")
        self.txt_output_name.setMaximumHeight(30)
        output_layout.addWidget(lbl_output)
        output_layout.addWidget(self.txt_output_name)
        scan_layout.addLayout(output_layout)
        
        controls_layout.addWidget(scan_grp)

        self.btn_analyze = QPushButton("Drill Down (Start Scan Engine)")
        self.btn_analyze.setIcon(self.logo_icon)
        self.btn_analyze.setMinimumHeight(50)
        self.btn_analyze.clicked.connect(self.toggle_analysis)
        self.btn_analyze.setStyleSheet("QPushButton { font-weight: bold; font-size: 14px; }")
        controls_layout.addWidget(self.btn_analyze)

        self.lbl_heartbeat = QLabel("Status: Idle")
        self.lbl_heartbeat.setStyleSheet("color: #aaaaaa; font-style: italic;")
        self.lbl_heartbeat.setAlignment(Qt.AlignCenter)
        controls_layout.addWidget(self.lbl_heartbeat)

        self.btn_open_folder = QPushButton("Open Official Output Directory")
        self.btn_open_folder.clicked.connect(self.open_output_folder)
        controls_layout.addWidget(self.btn_open_folder)

        controls_layout.addWidget(QLabel("Operation Logs & Performance Monitoring:"))
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet("""
            background-color: #1e1e1e; 
            color: #00ff00; 
            font-family: Consolas, Courier New, monospace; 
            font-size: 12px;
            border-radius: 5px;
            padding: 5px;
        """)
        controls_layout.addWidget(self.txt_log)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        controls_layout.addWidget(self.progress_bar)

        splitter.addWidget(controls_panel)
        splitter.setSizes([600, 450])

    def update_output_extension(self, text):
        current_name = self.txt_output_name.toPlainText().strip()
        base_name = os.path.splitext(current_name)[0]
        ext = text.lower()
        self.txt_output_name.setPlainText(f"{base_name}.{ext}")
        
        if ext in ["json", "csv"]:
            self.chk_minify.setEnabled(True)
        else:
            self.chk_minify.setChecked(False)
            self.chk_minify.setEnabled(False)

    def go_to_path(self):
        path = self.txt_search_path.text().strip()
        if not os.path.exists(path):
            QMessageBox.warning(self, "Invalid Path", f"The path unreadable or does not exist:\n{path}")
            return
        idx = self.model.index(path)
        if idx.isValid():
            self.tree.scrollTo(idx)
            self.tree.selectionModel().select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)
            self.tree.expand(idx)

    def search_directories(self):
        search_term = self.txt_search_path.text().strip().lower()
        if not search_term: return
        selected_paths = self.get_selected_paths()
        if selected_paths:
            root_idx = self.model.index(selected_paths[0])
            self.collapse_recursive(root_idx, search_term)

    def collapse_recursive(self, index, term):
        if not index.isValid(): return
        name = self.model.fileName(index).lower()
        if term in name:
            self.tree.expand(index)

    def on_item_double_clicked(self, index):
        if self.model.isDir(index):
            path = self.model.filePath(index)
            self.tree.scrollTo(self.model.index(path))

    def get_parametric_options(self):
        return {
            "include_path": self.chk_include_path.isChecked(),
            "include_date": self.chk_include_date.isChecked(),
            "include_bytes": self.chk_include_bytes.isChecked(),
            "include_readable": self.chk_include_readable.isChecked(),
            "include_extension": self.chk_include_extension.isChecked(),
            "export_format": self.cmb_format.currentText(),
            "minify_output": self.chk_minify.isChecked()
        }

    def get_selected_paths(self):
        indexes = self.tree.selectionModel().selectedIndexes()
        selected_paths = []
        for index in indexes:
            if index.column() == 0:
                path = self.model.filePath(index)
                if path not in selected_paths:
                    selected_paths.append(path)
        return selected_paths

    def toggle_analysis(self):
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.cancel()
            self.btn_analyze.setEnabled(False)
            self.btn_analyze.setText("Aborting... (Safely unwinding stack)")
            self.btn_analyze.setStyleSheet("background-color: #8B0000; color: white;")
            self.lbl_heartbeat.setText("Status: Halting operations...")
        else:
            self.start_analysis()

    def update_heartbeat(self, msg):
        self.lbl_heartbeat.setText(f"Status: {msg}")

    def update_phase(self, phase_type):
        """Switches the UI progress bar between indeterminate and determinate modes."""
        if phase_type == "INDETERMINATE":
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setTextVisible(False)
        elif phase_type == "DETERMINATE":
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_bar.setTextVisible(True)

    def start_analysis(self):
        selected_paths = self.get_selected_paths()
        if not selected_paths:
            QMessageBox.warning(self, "Extraction Error", "Please use the official navigator to select at least one directory for analysis.")
            return

        depth = self.spin_depth.value()
        output_file_name = self.txt_output_name.toPlainText().strip()
        
        expected_ext = f".{self.cmb_format.currentText().lower()}"
        if not output_file_name.lower().endswith(expected_ext):
            output_file_name += expected_ext
            self.txt_output_name.setPlainText(output_file_name)

        save_path = os.path.join(os.getcwd(), output_file_name)

        self.btn_analyze.setText("ABORT DRILL (Cancel Scan)")
        self.btn_analyze.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold;") 
        
        self.grp_options.setEnabled(False)
        self.cmb_format.setEnabled(False)
        self.spin_depth.setEnabled(False)
        self.txt_output_name.setEnabled(False)
        self.txt_log.clear()
        
        self.progress_bar.setVisible(True)
        self.lbl_heartbeat.setText("Status: Engine Started...")

        filtering_options = self.get_parametric_options()

        self.worker = ScanEngine(selected_paths, depth, save_path, filtering_options)
        
        # Connect the new signal slots
        self.worker.phase_signal.connect(self.update_phase)
        self.worker.progress_signal.connect(self.progress_bar.setValue)
        self.worker.heartbeat_signal.connect(self.update_heartbeat) 
        self.worker.log_signal.connect(self.txt_log.append)
        self.worker.finished_signal.connect(self.analysis_finished)
        
        self.worker.start()

    def analysis_finished(self, data):
        self.btn_analyze.setEnabled(True)
        self.btn_analyze.setText("Drill Down (Start Scan Engine)")
        self.btn_analyze.setStyleSheet("") 
        
        self.grp_options.setEnabled(True)
        self.cmb_format.setEnabled(True)
        self.spin_depth.setEnabled(True)
        self.txt_output_name.setEnabled(True)
        
        self.progress_bar.setVisible(False)
        self.lbl_heartbeat.setText("Status: Idle")
        
        if hasattr(self.worker, '_is_cancelled') and self.worker._is_cancelled:
            QMessageBox.warning(self, "Scan Aborted", f"The operation was safely aborted by the user.\nPartial data has been saved to: {os.path.basename(self.worker.save_path)}")
        elif "error" in data:
            QMessageBox.critical(self, "Export Error", f"An error occurred during export:\n{data['error']}")
        else:
            QMessageBox.information(self, "Scan Complete", f"High-performance extraction complete. Official report saved as '{os.path.basename(self.worker.save_path)}'.")

    def open_output_folder(self):
        output_folder = os.getcwd()
        if sys.platform == "win32":
            os.startfile(output_folder)
        elif sys.platform == "darwin":
            os.system(f"open '{output_folder}'")
        else:
            os.system(f"xdg-open '{output_folder}'")

if __name__ == "__main__":
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    app = QApplication(sys.argv)
    app.setStyle("Fusion") 
    analyzer = PathDrillApp()
    analyzer.show()
    sys.exit(app.exec())
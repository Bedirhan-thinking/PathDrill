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
sys.setrecursionlimit(100000)

# --------------------------------------------------------------------------
# PathDrill OFFICIAL LOGO (Scalable Icon Data - Base64)
# --------------------------------------------------------------------------
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
    progress_signal = Signal(int)
    log_signal = Signal(str)
    finished_signal = Signal(dict)

    def __init__(self, target_paths, max_depth, save_path, options):
        super().__init__()
        self.target_paths = target_paths
        self.max_depth = max_depth
        self.save_path = save_path
        self.options = options # Dictionary containing metadata options and export format

    def build_tree(self, current_path, current_depth):
        """Recursively builds a tree dictionary for the given path using DFS."""
        name = os.path.basename(current_path)
        node = {"name": name if name else current_path}
        
        # FIXED: Use os.path.normpath to respect OS-specific separators instead of forcing '/'
        if self.options.get("include_path", True):
            node["full_path"] = os.path.normpath(current_path)
        
        try:
            # os.stat is called once to gather all metadata to minimize I/O overhead
            stats = os.stat(current_path)
            
            # Parametric Filtering - Only add metadata if selected in UI
            if self.options.get("include_date", True):
                node["last_modified"] = datetime.fromtimestamp(stats.st_mtime).isoformat()
            if self.options.get("include_bytes", True):
                node["size_bytes"] = stats.st_size
            if self.options.get("include_readable", True):
                node["size_readable"] = format_size(stats.st_size)
        except OSError:
            node["error"] = "Metadata unreadable"
            return node

        if os.path.isdir(current_path):
            node["type"] = "directory"
            
            if self.max_depth != -1 and current_depth >= self.max_depth:
                return node

            node["contents"] = []
            try:
                # High-performance directory traversal using os.scandir
                with os.scandir(current_path) as scanner:
                    for item in scanner:
                        node["contents"].append(self.build_tree(item.path, current_depth + 1))
            except PermissionError:
                node["error"] = "Access Denied"
        else:
            node["type"] = "file"
            if self.options.get("include_extension", True):
                node["extension"] = os.path.splitext(current_path)[1].lower()

        return node

    # --- EXPORT STRATEGIES ---

    def export_to_json(self, data, file_path):
        """Dumps the hierarchical tree to a JSON file."""
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def export_to_csv(self, data, file_path):
        """Flattens the hierarchical tree to a 2D matrix and exports as CSV."""
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
                if "contents" in node:
                    flatten(node["contents"])
        
        flatten(data["scan_results"])
        
        # utf-8-sig is used so Excel recognizes the UTF-8 encoding properly
        with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
            fieldnames = ["Name", "Type", "Full Path", "Size (Bytes)", "Size (Readable)", "Last Modified", "Extension", "Error"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def export_to_txt(self, data, file_path):
        """Generates a visual ASCII-like tree representation."""
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
        """Generates a Markdown file with bulleted lists and folder/file icons."""
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
                    
                    if "contents" in node:
                        write_md(node["contents"], depth + 1)

            write_md(data["scan_results"])

    def run(self):
        """Main execution loop for the thread."""
        start_time = datetime.now()
        hierarchy_list = []
        total = len(self.target_paths)
        
        self.log_signal.emit(f"### PathDrill OFFICIAL Scan Started: {start_time.strftime('%H:%M:%S')} ###")
        self.log_signal.emit(f"Targeting {total} root paths with parametric filtering.")
        
        for i, path in enumerate(self.target_paths):
            if not os.path.exists(path): continue
            self.log_signal.emit(f"Scanning ({i+1}/{total}): {path}")
            hierarchy_list.append(self.build_tree(path, 0))
            self.progress_signal.emit(int(((i + 1) / total) * 100))

        final_data = {
            "report_info": {
                "tool": "PathDrill-Extractor",
                "creation_datetime": start_time.isoformat(),
                "scanned_paths_count": len(self.target_paths),
                "defined_depth": self.max_depth if self.max_depth != -1 else "Unlimited",
                "metadata_filtering": self.options,
                "status": "Completed Successfully"
            },
            "scan_results": hierarchy_list
        }

        # Strategy Pattern Selection based on UI choice
        export_format = self.options.get("export_format", "JSON")
        
        try:
            if export_format == "JSON":
                self.export_to_json(final_data, self.save_path)
            elif export_format == "CSV":
                self.export_to_csv(final_data, self.save_path)
            elif export_format == "TXT":
                self.export_to_txt(final_data, self.save_path)
            elif export_format == "MD":
                self.export_to_md(final_data, self.save_path)
            
            elapsed_time = datetime.now() - start_time
            self.log_signal.emit(f"### Completed in {elapsed_time.total_seconds():.3f} seconds. ###")
            self.log_signal.emit(f"Official report saved: {self.save_path}")
            self.finished_signal.emit(final_data)
            
        except Exception as e:
            self.log_signal.emit(f"[!] Export Error: {str(e)}")
            self.finished_signal.emit({"error": str(e)})


class PathDrillApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PathDrill - Advanced Path Extraction & Ad-hoc Analysis Tool")
        self.resize(1100, 750)

        # Set official logo (embedded base64)
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
        
        # 1. Official Logo & Quick Search Bar
        nav_layout = QHBoxLayout()
        logo_label = QLabel()
        if not qpixmap.isNull():
            logo_label.setPixmap(qpixmap.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        nav_layout.addWidget(logo_label)

        self.txt_search_path = QLineEdit()
        self.txt_search_path.setPlaceholderText("Paste full path or start typing...")
        self.txt_search_path.setToolTip("Paste full path and press Enter to jump.")
        self.txt_search_path.returnPressed.connect(self.go_to_path) # Jump to path on Enter
        self.txt_search_path.textChanged.connect(self.search_directories) # Quick name search
        nav_layout.addWidget(self.txt_search_path)
        
        self.btn_search = QPushButton("Find")
        self.btn_search.clicked.connect(self.search_directories)
        nav_layout.addWidget(self.btn_search)
        
        file_layout.addLayout(nav_layout)

        # 2. Explorer Tree
        self.model = QFileSystemModel()
        self.model.setRootPath("") # All drives
        self.model.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot | QDir.Hidden)
        
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setAnimated(True)
        self.tree.setIndentation(20)
        self.tree.setSortingEnabled(True)
        self.tree.setSelectionMode(QTreeView.ExtendedSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.doubleClicked.connect(self.on_item_double_clicked) # Navigation
        
        initial_index = self.model.index(os.getcwd())
        self.tree.scrollTo(initial_index)
        self.tree.resizeColumnToContents(0)

        file_layout.addWidget(self.tree)
        splitter.addWidget(file_manager_widget)

        # --- RIGHT SIDE: Controls, Parametric Options & Logs ---
        controls_panel = QWidget()
        controls_layout = QVBoxLayout(controls_panel)
        controls_layout.setContentsMargins(10, 0, 0, 0)
        
        # 1. Official Logo Banner
        banner_label = QLabel()
        if not qpixmap.isNull():
            banner_label.setPixmap(qpixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        banner_label.setAlignment(Qt.AlignCenter)
        controls_layout.addWidget(banner_label)
        
        # 2. Parametric Extraction Options (Metadata Filter)
        self.grp_options = QGroupBox("Metadata Extraction Parameters")
        options_layout = QVBoxLayout(self.grp_options)
        
        self.chk_include_path = QCheckBox("Include Full Absolute Path")
        self.chk_include_path.setChecked(True)
        options_layout.addWidget(self.chk_include_path)
        
        self.chk_include_date = QCheckBox("Include Last Modification Date/Time")
        self.chk_include_date.setChecked(True)
        options_layout.addWidget(self.chk_include_date)
        
        self.chk_include_bytes = QCheckBox("Include Raw Size (Bytes)")
        self.chk_include_bytes.setChecked(True)
        options_layout.addWidget(self.chk_include_bytes)
        
        self.chk_include_readable = QCheckBox("Include Readable Size (KB/MB)")
        self.chk_include_readable.setChecked(True)
        options_layout.addWidget(self.chk_include_readable)
        
        self.chk_include_extension = QCheckBox("Include File Extension")
        self.chk_include_extension.setChecked(True)
        options_layout.addWidget(self.chk_include_extension)
        
        controls_layout.addWidget(self.grp_options)

        # 3. Basic Scan Controls (Depth & Output Name)
        scan_grp = QGroupBox("Core Scan Controls")
        scan_layout = QVBoxLayout(scan_grp)
        
        # Combo box for Format selection
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
        self.spin_depth.setValue(2) # Default depth 2
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

        # 4. Action Buttons
        self.btn_analyze = QPushButton("Drill Down (Start Scan Engine)")
        self.btn_analyze.setIcon(self.logo_icon)
        self.btn_analyze.setMinimumHeight(50)
        self.btn_analyze.clicked.connect(self.start_analysis)
        controls_layout.addWidget(self.btn_analyze)

        self.btn_open_folder = QPushButton("Open Official Output Directory")
        self.btn_open_folder.clicked.connect(self.open_output_folder)
        controls_layout.addWidget(self.btn_open_folder)

        # 5. Hacker-Aesthetic Logs & Progress
        controls_layout.addWidget(QLabel("Operation Logs & Performance Monitoring:"))
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        
        self.txt_log.setStyleSheet("""
            background-color: #1e1e1e; 
            color: #00ff00; 
            font-family: Consolas, Courier New, monospace; 
            font-size: 13px;
            border-radius: 5px;
            padding: 5px;
        """)
        controls_layout.addWidget(self.txt_log)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        controls_layout.addWidget(self.progress_bar)

        splitter.addWidget(controls_panel)
        splitter.setSizes([600, 400]) # Initial split ratio

    # --- Directory Manager: Navigation & Quick Acess ---
    def update_output_extension(self, text):
        """Automatically updates the file extension in the text box when format changes."""
        current_name = self.txt_output_name.toPlainText().strip()
        base_name = os.path.splitext(current_name)[0]
        ext = text.lower()
        self.txt_output_name.setPlainText(f"{base_name}.{ext}")

    def go_to_path(self):
        """Official Navigation Method. Jumps to path pasted in search bar."""
        path = self.txt_search_path.text().strip()
        if not os.path.exists(path):
            QMessageBox.warning(self, "Invalid Path", f"The path unreadable or does not exist:\n{path}")
            return
        
        idx = self.model.index(path)
        if idx.isValid():
            self.tree.scrollTo(idx)
            self.tree.selectionModel().select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)
            # Expand to show the path contents
            self.tree.expand(idx)

    def search_directories(self):
        """Quick Access Method. Collapses/Expands tree to find by name."""
        search_term = self.txt_search_path.text().strip().lower()
        
        # Simplified quick search
        if not search_term:
            return
            
        selected_paths = self.get_selected_paths()
        if selected_paths:
            root_idx = self.model.index(selected_paths[0])
            self.collapse_recursive(root_idx, search_term)

    def collapse_recursive(self, index, term):
        """Helper to recursively expand directories matching search term."""
        if not index.isValid(): return
        
        name = self.model.fileName(index).lower()
        if term in name:
            self.tree.expand(index)

    def on_item_double_clicked(self, index):
        """Explorer Shortcut: Double click moves directory view."""
        if self.model.isDir(index):
            path = self.model.filePath(index)
            self.tree.scrollTo(self.model.index(path))

    # --- Core Scan Engine & Analysis ---
    def get_parametric_options(self):
        """Collects metadata filter state and export format from UI."""
        return {
            "include_path": self.chk_include_path.isChecked(),
            "include_date": self.chk_include_date.isChecked(),
            "include_bytes": self.chk_include_bytes.isChecked(),
            "include_readable": self.chk_include_readable.isChecked(),
            "include_extension": self.chk_include_extension.isChecked(),
            "export_format": self.cmb_format.currentText()
        }

    def get_selected_paths(self):
        """Officially selects paths for high-performance drilling."""
        indexes = self.tree.selectionModel().selectedIndexes()
        selected_paths = []
        for index in indexes:
            if index.column() == 0:
                path = self.model.filePath(index)
                if path not in selected_paths:
                    selected_paths.append(path)
        return selected_paths

    def start_analysis(self):
        """Officially launches the high-performance Drilling Engine."""
        selected_paths = self.get_selected_paths()
        if not selected_paths:
            QMessageBox.warning(self, "Extraction Error", "Please use the official navigator to select at least one directory for analysis.")
            return

        depth = self.spin_depth.value()
        output_file_name = self.txt_output_name.toPlainText().strip()
        
        # Ensure correct extension is enforced
        expected_ext = f".{self.cmb_format.currentText().lower()}"
        if not output_file_name.lower().endswith(expected_ext):
            output_file_name += expected_ext
            self.txt_output_name.setPlainText(output_file_name)

        save_path = os.path.join(os.getcwd(), output_file_name)

        # Freeze UI during the "drill"
        self.btn_analyze.setEnabled(False)
        self.grp_options.setEnabled(False)
        self.cmb_format.setEnabled(False)
        self.spin_depth.setEnabled(False)
        self.txt_output_name.setEnabled(False)
        self.txt_log.clear()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)

        # Get Parametric Filtering options
        filtering_options = self.get_parametric_options()

        # Start official Worker thread
        self.worker = ScanEngine(selected_paths, depth, save_path, filtering_options)
        self.worker.progress_signal.connect(self.progress_bar.setValue)
        self.worker.log_signal.connect(self.txt_log.append)
        self.worker.finished_signal.connect(self.analysis_finished)
        self.worker.start()

    def analysis_finished(self, data):
        """Thaws UI and notifies successful completion."""
        self.btn_analyze.setEnabled(True)
        self.grp_options.setEnabled(True)
        self.cmb_format.setEnabled(True)
        self.spin_depth.setEnabled(True)
        self.txt_output_name.setEnabled(True)
        self.progress_bar.setVisible(False)
        QMessageBox.information(self, "Scan Complete", f"High-performance extraction complete. Official report saved as '{os.path.basename(self.worker.save_path)}'.")

    def open_output_folder(self):
        """Officially opens the current execution context folder."""
        output_folder = os.getcwd()
        if sys.platform == "win32":
            os.startfile(output_folder)
        elif sys.platform == "darwin":
            os.system(f"open '{output_folder}'")
        else:
            os.system(f"xdg-open '{output_folder}'")

if __name__ == "__main__":
    # High DPI dynamic scaling
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion") # Official professional style

    analyzer = PathDrillApp()
    analyzer.show()
    
    sys.exit(app.exec())
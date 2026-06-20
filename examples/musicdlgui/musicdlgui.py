'''
Function:
    Implementation of MusicdlGUI
Author:
    Zhenchao Jin
WeChat Official Account (微信公众号):
    Charles的皮卡丘
'''
import os
import sys
import requests
import json
from threading import Event
from PyQt6.QtGui import *
from PyQt6.QtCore import *
from musicdl import musicdl
from PyQt6.QtWidgets import *
from musicdl.modules.utils.misc import sanitize_filepath


# ---------------------------------------------------------------------------
# Settings helpers — cache dir, load / save, dialog
# ---------------------------------------------------------------------------

# 品质名称映射（用于显示）
QUALITY_NAMES = {
    'jymaster': '极品音质',
    'dolby': '杜比全景声',
    'sky': '天空音质',
    'jyeffect': '高解析音质',
    'hires': 'Hi-Res',
    'lossless': '无损音质',
    'exhigh': '超高音质',
    'standard': '标准音质'
}

def get_app_cache_dir():
    """获取系统默认用户缓存目录"""
    if sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
    elif sys.platform == 'darwin':
        base = os.path.expanduser('~/Library/Caches')
    else:
        base = os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache'))
    return os.path.join(base, 'musicdlgui')


def load_settings():
    """从系统缓存目录加载设置"""
    cache_dir = get_app_cache_dir()
    config_path = os.path.join(cache_dir, 'config.json')
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'download_dir': os.path.expanduser('~/Downloads'), 'checked_sources': ['NeteaseMusicClient'], 'min_file_size_mb': 0, 'return_all_qualities': True}


def save_settings(settings):
    """保存设置到系统缓存目录"""
    cache_dir = get_app_cache_dir()
    os.makedirs(cache_dir, exist_ok=True)
    config_path = os.path.join(cache_dir, 'config.json')
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class SettingsDialog(QDialog):
    """设置对话框"""
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle('设置')
        self.resize(450, 200)
        self.setModal(True)
        layout = QVBoxLayout(self)

        # 下载目录
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel('下载目录:'))
        self.dir_edit = QLineEdit(settings.get('download_dir', os.path.expanduser('~/Downloads')))
        dir_layout.addWidget(self.dir_edit)
        browse_btn = QPushButton('浏览...')
        browse_btn.clicked.connect(self.browse_dir)
        dir_layout.addWidget(browse_btn)
        layout.addLayout(dir_layout)

        # 最小文件大小（MB）
        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel('最小文件大小(MB):'))
        self.min_size_spin = QSpinBox()
        self.min_size_spin.setRange(0, 100)  # 0-100MB范围
        self.min_size_spin.setValue(int(settings.get('min_file_size_mb', 0)))
        self.min_size_spin.setSuffix(' MB')
        size_layout.addWidget(self.min_size_spin)
        size_layout.addWidget(QLabel('(0表示不限制)'))
        layout.addLayout(size_layout)

        # 显示所有品质选项
        quality_layout = QHBoxLayout()
        self.quality_checkbox = QCheckBox('显示所有可用品质（否则只显示最高品质）')
        self.quality_checkbox.setChecked(settings.get('return_all_qualities', True))
        quality_layout.addWidget(self.quality_checkbox)
        layout.addLayout(quality_layout)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QPushButton('保存')
        save_btn.clicked.connect(self.save_and_close)
        btn_layout.addWidget(save_btn)
        cancel_btn = QPushButton('取消')
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def browse_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, '选择下载目录', self.dir_edit.text())
        if dir_path:
            self.dir_edit.setText(dir_path)

    def save_and_close(self):
        self.settings['download_dir'] = self.dir_edit.text()
        self.settings['min_file_size_mb'] = self.min_size_spin.value()
        self.settings['return_all_qualities'] = self.quality_checkbox.isChecked()
        save_settings(self.settings)
        self.accept()


# ---------------------------------------------------------------------------
# SearchWorker - runs search in background thread to avoid GUI freeze
# ---------------------------------------------------------------------------
class SearchWorker(QThread):
    search_finished = pyqtSignal(object, str)
    partial_result = pyqtSignal(str, list)  # (source_name, list_of_SongInfo_dicts)

    def __init__(self, music_sources, keyword, search_rules=None):
        super().__init__()
        self.music_sources = music_sources
        self.keyword = keyword
        self.search_rules = search_rules or {}
        self.music_client = None
        self.stop_event = Event()
        self._accumulated = {}  # {source: [SongInfo, ...]} for dedup

    def stop(self):
        self.stop_event.set()

    def run(self):
        self.music_client = musicdl.MusicClient(music_sources=self.music_sources, search_rules=self.search_rules)
        import inspect
        sig = inspect.signature(self.music_client.search)
        params = list(sig.parameters.keys())
        if 'stop_event' in params:
            results = self.music_client.search(
                keyword=self.keyword,
                stop_event=self.stop_event,
                on_result_callback=self._on_partial_result
            )
        else:
            results = self.music_client.search(keyword=self.keyword)
        self.search_finished.emit(results, '')

    def _on_partial_result(self, source, song_infos):
        """Called from search thread when new results arrive."""
        if self.stop_event.is_set():
            return
        # Dedup within accumulated results
        existing_ids = set()
        if source in self._accumulated:
            for si in self._accumulated[source]:
                existing_ids.add(getattr(si, 'identifier', id(si)))
        new_infos = []
        for si in song_infos:
            sid = getattr(si, 'identifier', id(si))
            if sid not in existing_ids:
                existing_ids.add(sid)
                new_infos.append(si)
        self._accumulated.setdefault(source, []).extend(new_infos)
        if new_infos:
            self.partial_result.emit(source, new_infos)

    def get_music_client(self):
        return self.music_client


# ---------------------------------------------------------------------------
# MusicdlGUI
# ---------------------------------------------------------------------------
class MusicdlGUI(QWidget):
    def __init__(self):
        super(MusicdlGUI, self).__init__()
        # initialize
        self.setWindowTitle('MusicdlGUI —— Charles的皮卡丘')
        self.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), 'icon.ico')))
        self.resize(950, 520)
        self.initialize()
        # settings (auto-load)
        self.settings = load_settings()
        self.download_dir = self.settings.get('download_dir', os.path.expanduser('~/Downloads'))
        # search sources
        self.src_names = ['QQMusicClient', 'KuwoMusicClient', 'MiguMusicClient', 'QianqianMusicClient', 'KugouMusicClient']
        self.label_src = QLabel('Search Engine:')
        self.check_boxes = []
        checked_sources = self.settings.get('checked_sources', ['NeteaseMusicClient'])
        for src in self.src_names:
            cb = QCheckBox(src, self)
            cb.setCheckState(Qt.CheckState.Checked if src in checked_sources else Qt.CheckState.Unchecked)
            self.check_boxes.append(cb)
        # input boxes
        self.label_keyword = QLabel('Keywords:')
        self.lineedit_keyword = QLineEdit()
        # Ctrl+Enter 快捷键触发搜索
        self.search_shortcut = QShortcut(QKeySequence('Ctrl+Return'), self.lineedit_keyword)
        self.search_shortcut.activated.connect(self.search)
        self.button_keyword = QPushButton('Search')
        self.button_stop = QPushButton('Stop')
        self.button_stop.setEnabled(False)
        self.button_settings = QPushButton('⚙ 设置')
        # search results table
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(8)
        self.results_table.setHorizontalHeaderLabels(['ID', 'Singers', 'Songname', 'Filesize', 'Duration', 'Album', 'Quality', 'Source'])
        self.results_table.horizontalHeader().setStyleSheet("QHeaderView::section{background:skyblue;color:black;}")
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # 启用列标题点击排序
        self.results_table.horizontalHeader().setSectionsClickable(True)
        self.results_table.horizontalHeader().setSortIndicatorShown(True)
        self.results_table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        # mouse click menu
        self.context_menu = QMenu(self)
        self.action_download = self.context_menu.addAction('Download')
        # progress bar
        self.bar_download = QProgressBar(self)
        self.label_download = QLabel('Download progress:')
        # status label for search progress
        self.label_status = QLabel('')
        # grid
        grid = QGridLayout()
        grid.addWidget(self.label_src, 0, 0, 1, 1)
        # 复选框用水平布局包裹，避免Grid列拉伸导致的间距不均
        cb_layout = QHBoxLayout()
        cb_layout.setSpacing(12)
        for cb in self.check_boxes:
            cb_layout.addWidget(cb)
        cb_widget = QWidget()
        cb_widget.setLayout(cb_layout)
        grid.addWidget(cb_widget, 0, 1, 1, len(self.src_names))
        grid.addWidget(self.label_keyword, 1, 0, 1, 1)
        grid.addWidget(self.lineedit_keyword, 1, 1, 1, len(self.src_names)-2)
        grid.addWidget(self.button_keyword, 1, len(self.src_names)-2, 1, 1)
        grid.addWidget(self.button_stop, 1, len(self.src_names)-1, 1, 1)
        grid.addWidget(self.button_settings, 1, len(self.src_names), 1, 1)
        grid.addWidget(self.label_status, 2, 0, 1, len(self.src_names)+2)
        grid.addWidget(self.label_download, 3, 0, 1, 1)
        grid.addWidget(self.bar_download, 3, 1, 1, len(self.src_names))
        grid.addWidget(self.results_table, 4, 0, len(self.src_names), len(self.src_names)+2)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(4, 1)
        self.grid = grid
        self.setLayout(grid)
        # connect
        self.button_keyword.clicked.connect(self.search)
        self.button_stop.clicked.connect(self.stop_search)
        self.results_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_table.customContextMenuRequested.connect(self.mouseclick)
        self.action_download.triggered.connect(self.download)
        self.button_settings.clicked.connect(self.open_settings)
        # search worker
        self.search_worker = None
    def initialize(self):
        self.search_results = {}
        self.music_records = {}
        self.selected_music_idx = -10000
        self.music_client = None
        # 排序状态
        self._sort_column = -1
        self._sort_order = Qt.SortOrder.AscendingOrder

    def _parse_file_size_to_mb(self, file_size_str):
        """将文件大小字符串转换为MB数值"""
        if not file_size_str:
            return 0
        try:
            # 处理类似 "5.23MB" 或 "1024KB" 的格式
            file_size_str = str(file_size_str).upper().strip()
            if 'GB' in file_size_str:
                return float(file_size_str.replace('GB', '').strip()) * 1024
            elif 'MB' in file_size_str:
                return float(file_size_str.replace('MB', '').strip())
            elif 'KB' in file_size_str:
                return float(file_size_str.replace('KB', '').strip()) / 1024
            elif 'B' in file_size_str:
                return float(file_size_str.replace('B', '').strip()) / (1024 * 1024)
            else:
                # 假设已经是MB
                return float(file_size_str)
        except:
            return 0

    def _filter_by_min_file_size(self, song_info):
        """根据最小文件大小设置过滤搜索结果"""
        min_size_mb = self.settings.get('min_file_size_mb', 0)
        if min_size_mb <= 0:
            return True  # 不限制
        file_size_mb = self._parse_file_size_to_mb(song_info.get('file_size', ''))
        return file_size_mb >= min_size_mb

    def _parse_duration_to_seconds(self, duration_str):
        """将时长字符串（如 04:30 或 1:02:30）转换为总秒数"""
        if not duration_str:
            return 0
        try:
            parts = str(duration_str).strip().split(':')
            if len(parts) == 3:  # HH:MM:SS
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:  # MM:SS
                return int(parts[0]) * 60 + int(parts[1])
            else:
                return float(duration_str)
        except (ValueError, TypeError):
            return 0

    def _get_sort_key_for_row(self, row, column):
        """获取指定行、列的排序键值（用于自定义排序比较）"""
        item = self.results_table.item(row, column)
        if item is None:
            return ''
        text = item.text()
        if column == 0:  # ID列 - 按数值排序
            try:
                return (0, int(text))
            except ValueError:
                return (0, 0)
        elif column == 3:  # Filesize列 - 按解析后的MB数值排序
            return (1, self._parse_file_size_to_mb(text))
        elif column == 4:  # Duration列 - 按总秒数排序
            return (2, self._parse_duration_to_seconds(text))
        else:  # 其他列 - 按字符串排序
            return (3, text.lower())

    '''点击列表标题时按该列排序'''
    def on_header_clicked(self, column_index):
        # 切换排序方向：同一切换方向，不同列默认升序
        if column_index == self._sort_column:
            self._sort_order = Qt.SortOrder.DescendingOrder if self._sort_order == Qt.SortOrder.AscendingOrder else Qt.SortOrder.AscendingOrder
        else:
            self._sort_column = column_index
            self._sort_order = Qt.SortOrder.AscendingOrder

        # 保存当前music_records的快照，用于重建映射
        old_music_records = dict(self.music_records)

        # 收集所有行数据并按排序列的值排序
        row_count = self.results_table.rowCount()
        rows_data = []
        for row in range(row_count):
            sort_key = self._get_sort_key_for_row(row, column_index)
            # 收集每行的所有单元格文本和对应的 music_records key
            row_texts = []
            for col in range(self.results_table.columnCount()):
                item = self.results_table.item(row, col)
                row_texts.append(item.text() if item else '')
            # 找到该行在 music_records 中对应的 key
            record_key = None
            for key, val in self.music_records.items():
                # 通过ID列匹配
                id_item = self.results_table.item(row, 0)
                if id_item and key == id_item.text():
                    record_key = key
                    break
            rows_data.append((sort_key, row_texts, record_key))

        # 排序
        reverse = (self._sort_order == Qt.SortOrder.DescendingOrder)
        rows_data.sort(key=lambda x: x[0], reverse=reverse)

        # 重新填充表格
        for new_row, (_, row_texts, record_key) in enumerate(rows_data):
            for col, text in enumerate(row_texts):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                self.results_table.setItem(new_row, col, item)

        # 更新 music_records 的映射关系 + 更新ID列为新的行号
        self.music_records = {}
        for new_row, (_, row_texts, _) in enumerate(rows_data):
            old_id_text = row_texts[0]  # 原来的ID文本
            # 从旧的music_records中取出数据（用旧ID作为key）
            old_record = old_music_records.pop(old_id_text, None)
            if old_record is not None:
                self.music_records[str(new_row)] = old_record
            # 更新ID列显示为新的行号
            id_item = self.results_table.item(new_row, 0)
            if id_item:
                id_item.setText(str(new_row))

        # 在表头显示排序指示（通过setSortIndicator）
        self.results_table.horizontalHeader().setSortIndicator(column_index, self._sort_order)

    '''搜索完成后自动多列排序：Singers(升序) -> Filesize(升序)'''
    def _auto_sort_after_search(self):
        row_count = self.results_table.rowCount()
        if row_count <= 1:
            return

        # 保存当前music_records的快照
        old_music_records = dict(self.music_records)

        # 收集所有行数据，按多列生成排序键
        rows_data = []
        for row in range(row_count):
            # 排序键：(Singers字符串, Filesize数值)
            key_singers = ''
            singers_item = self.results_table.item(row, 1)
            if singers_item:
                key_singers = singers_item.text().lower()
            key_filesize = 0
            filesize_item = self.results_table.item(row, 3)
            if filesize_item:
                key_filesize = self._parse_file_size_to_mb(filesize_item.text())
            sort_key = (key_singers, key_filesize)

            row_texts = []
            for col in range(self.results_table.columnCount()):
                item = self.results_table.item(row, col)
                row_texts.append(item.text() if item else '')
            rows_data.append((sort_key, row_texts))

        # 按多键排序（均为升序）
        rows_data.sort(key=lambda x: x[0])

        # 重新填充表格
        for new_row, (_, row_texts) in enumerate(rows_data):
            for col, text in enumerate(row_texts):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                self.results_table.setItem(new_row, col, item)

        # 重建 music_records 映射 + 更新ID列
        self.music_records = {}
        for new_row, (_, row_texts) in enumerate(rows_data):
            old_id_text = row_texts[0]
            old_record = old_music_records.pop(old_id_text, None)
            if old_record is not None:
                self.music_records[str(new_row)] = old_record
            id_item = self.results_table.item(new_row, 0)
            if id_item:
                id_item.setText(str(new_row))

        # 更新排序状态，标记当前为Singers列升序
        self._sort_column = 1
        self._sort_order = Qt.SortOrder.AscendingOrder
        self.results_table.horizontalHeader().setSortIndicator(1, Qt.SortOrder.AscendingOrder)
    '''mouseclick'''
    def mouseclick(self):
        self.context_menu.move(QCursor().pos())
        self.context_menu.show()
    '''download'''
    def _get_unique_filepath(self, base_path):
        """生成不重复的文件路径，若已存在同名文件则追加数字后缀"""
        if not os.path.exists(base_path):
            return base_path
        directory = os.path.dirname(base_path)
        basename = os.path.basename(base_path)
        name, ext = os.path.splitext(basename)
        index = 1
        while True:
            new_name = f'{name}_{index}{ext}'
            new_path = os.path.join(directory, new_name)
            if not os.path.exists(new_path):
                return new_path
            index += 1

    def download(self):
        self.selected_music_idx = str(self.results_table.selectedItems()[0].row())
        song_info = self.music_records.get(self.selected_music_idx)
        with requests.get(song_info['download_url'], headers=self.music_client.music_clients[song_info['source']].default_download_headers, stream=True, verify=False) as resp:
            if resp.status_code == 200:
                total_size, chunk_size, download_size = int(resp.headers['content-length']), 1024, 0
                os.makedirs(self.download_dir, exist_ok=True)
                download_music_file_path = sanitize_filepath(os.path.join(self.download_dir, song_info['song_name']+'.'+song_info['ext']))

                # 检查是否已存在同名文件
                if os.path.exists(download_music_file_path):
                    existing_size = os.path.getsize(download_music_file_path)
                    if existing_size == total_size:
                        # 文件大小相同，跳过下载
                        print(f'[跳过重复] {song_info["song_name"]} 已存在且大小一致 ({existing_size} bytes)，忽略本次下载')
                        self.bar_download.setValue(0)
                        return
                    else:
                        # 大小不同，追加后缀避免覆盖
                        download_music_file_path = self._get_unique_filepath(download_music_file_path)

                with open(download_music_file_path, 'wb') as fp:
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        if not chunk: continue
                        fp.write(chunk)
                        download_size += len(chunk)
                        self.bar_download.setValue(int(download_size / total_size * 100))
        # 下载完成，播放提示音
        QApplication.beep()
        self.bar_download.setValue(0)
    '''on search finished'''
    def on_search_finished(self, results, error=''):
        # Cancel any pending stop watchdog
        if hasattr(self, '_stop_watchdog') and self._stop_watchdog:
            self._stop_watchdog.stop()
        # If we already displayed results incrementally, just finalize
        if self.search_results and sum(len(v) for v in self.search_results.values()) > 0:
            count = sum(len(v) for v in self.search_results.values())
            sources_with_results = [s for s, v in self.search_results.items() if v]
            sources_checked = [cb.text() for cb in self.check_boxes if cb.isChecked()]
            sources_failed = [s for s in sources_checked if s not in sources_with_results]
            self.button_keyword.setEnabled(True)
            self.button_keyword.setText('Search')
            self.button_stop.setEnabled(False)
            msg = f'Search complete — {count} results found.'
            if sources_failed:
                msg += f' (No results from: {", ".join(sources_failed)})'
            self.label_status.setText(msg)
            return

        self.search_results = results

        # showing with file size filter and quality expansion
        count, row = 0, 0
        return_all_qualities = self.settings.get('return_all_qualities', True)

        for per_source_search_results in self.search_results.values():
            # 展开所有品质或只保留主要结果
            expanded_results = []
            for r in per_source_search_results:
                if return_all_qualities and hasattr(r, 'episodes') and r.episodes:
                    # 添加主结果（最高品质）
                    if self._filter_by_min_file_size(r):
                        expanded_results.append(r)
                    # 添加其他品质
                    for ep in r.episodes:
                        ep_dict = ep.todict() if hasattr(ep, 'todict') else ep
                        if self._filter_by_min_file_size(ep_dict):
                            expanded_results.append(ep_dict)
                else:
                    if self._filter_by_min_file_size(r):
                        expanded_results.append(r)
            count += len(expanded_results)

        self.results_table.setRowCount(count)
        for _, (_, per_source_search_results) in enumerate(self.search_results.items()):
            # 展开所有品质或只保留主要结果
            for r in per_source_search_results:
                if return_all_qualities and hasattr(r, 'episodes') and r.episodes:
                    # 处理主结果
                    if self._filter_by_min_file_size(r):
                        row_data = [
                            str(row),
                            r['singers'],
                            r['song_name'],
                            r['file_size'],
                            r['duration'],
                            r['album'],
                            QUALITY_NAMES.get(getattr(r, 'raw_data', {}).get('quality', ''), r.get('quality', '')),
                            r['source'],
                        ]
                        for column, item in enumerate(row_data):
                            self.results_table.setItem(row, column, QTableWidgetItem(item))
                            self.results_table.item(row, column).setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                        self.music_records.update({str(row): r})
                        row += 1
                    # 处理其他品质
                    for ep in r.episodes:
                        ep_dict = ep.todict() if hasattr(ep, 'todict') else ep
                        if self._filter_by_min_file_size(ep_dict):
                            quality_label = QUALITY_NAMES.get(getattr(ep, 'raw_data', {}).get('quality', ''), '')
                            row_data = [
                                str(row),
                                ep_dict['singers'],
                                ep_dict['song_name'] + f' [{quality_label}]' if quality_label else ep_dict['song_name'],
                                ep_dict['file_size'],
                                ep_dict['duration'],
                                ep_dict['album'],
                                quality_label,
                                ep_dict['source'],
                            ]
                            for column, item in enumerate(row_data):
                                self.results_table.setItem(row, column, QTableWidgetItem(item))
                                self.results_table.item(row, column).setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                            self.music_records.update({str(row): ep_dict})
                            row += 1
                else:
                    # 传统模式：不过滤品质
                    if self._filter_by_min_file_size(r):
                        row_data = [
                            str(row),
                            r['singers'],
                            r['song_name'],
                            r['file_size'],
                            r['duration'],
                            r['album'],
                            '',
                            r['source'],
                        ]
                        for column, item in enumerate(row_data):
                            self.results_table.setItem(row, column, QTableWidgetItem(item))
                            self.results_table.item(row, column).setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                        self.music_records.update({str(row): r})
                        row += 1
        # re-enable button
        self.button_keyword.setEnabled(True)
        self.button_keyword.setText('Search')
        self.button_stop.setEnabled(False)
        msg = f'Search complete — {count} results found.'
        sources_checked = [cb.text() for cb in self.check_boxes if cb.isChecked()]
        sources_with_results = [s for s, v in self.search_results.items() if v]
        sources_failed = [s for s in sources_checked if s not in sources_with_results]
        if sources_failed:
            msg += f' (No results from: {", ".join(sources_failed)})'
        self.label_status.setText(msg)

        # 搜索完成后自动按 Singers(升序) -> Filesize(升序) 排序
        if count > 0:
            self._auto_sort_after_search()

    '''handle partial result (incremental display)'''
    def on_partial_result(self, source, song_infos):
        """Called when a source produces new results during search."""
        return_all_qualities = self.settings.get('return_all_qualities', True)
        for song_info in song_infos:
            # 应用文件大小过滤
            if not self._filter_by_min_file_size(song_info):
                continue

            # Accumulate in search_results
            self.search_results.setdefault(source, []).append(song_info)

            # Add main result row to table
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            quality_label = QUALITY_NAMES.get(getattr(song_info, 'raw_data', {}).get('quality', ''), '')
            row_data = [
                str(row),
                song_info['singers'],
                song_info['song_name'],
                song_info['file_size'],
                song_info['duration'],
                song_info['album'],
                quality_label,
                song_info['source'],
            ]
            for column, item in enumerate(row_data):
                self.results_table.setItem(row, column, QTableWidgetItem(item))
                self.results_table.item(row, column).setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            self.music_records.update({str(row): song_info})

            # If return_all_qualities and has episodes (other qualities), add them too
            if return_all_qualities and hasattr(song_info, 'episodes') and song_info.episodes:
                for ep in song_info.episodes:
                    ep_dict = ep.todict() if hasattr(ep, 'todict') else ep
                    if self._filter_by_min_file_size(ep_dict):
                        ep_row = self.results_table.rowCount()
                        self.results_table.insertRow(ep_row)
                        ep_quality = QUALITY_NAMES.get(getattr(ep, 'raw_data', {}).get('quality', ''), '')
                        ep_row_data = [
                            str(ep_row),
                            ep_dict['singers'],
                            ep_dict['song_name'] + f' [{ep_quality}]' if ep_quality else ep_dict['song_name'],
                            ep_dict['file_size'],
                            ep_dict['duration'],
                            ep_dict['album'],
                            ep_quality,
                            ep_dict['source'],
                        ]
                        for column, item in enumerate(ep_row_data):
                            self.results_table.setItem(ep_row, column, QTableWidgetItem(item))
                            self.results_table.item(ep_row, column).setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                        self.music_records.update({str(ep_row): ep_dict})

        total = sum(len(v) for v in self.search_results.values())
        self.label_status.setText(f'Searching... {total} results found so far.')

    '''stop search'''
    def stop_search(self):
        if self.search_worker and self.search_worker.isRunning():
            self.search_worker.stop()
            self.label_status.setText('Stopping search...')
            self.button_stop.setEnabled(False)
            # Watchdog: if the worker doesn't finish within 10 seconds,
            # force-terminate it and restore the UI
            self._stop_watchdog = QTimer(self)
            self._stop_watchdog.setSingleShot(True)
            self._stop_watchdog.timeout.connect(self._on_stop_timeout)
            self._stop_watchdog.start(10000)  # 10 seconds
    '''force stop timeout handler'''
    def _on_stop_timeout(self):
        """Called when the search worker doesn't finish within the watchdog period after stop."""
        if self.search_worker and self.search_worker.isRunning():
            self.search_worker.terminate()
            self.label_status.setText('Search stopped (forced).')
        else:
            self.label_status.setText('Search stopped.')
        self.button_keyword.setEnabled(True)
        self.button_keyword.setText('Search')
        self.button_stop.setEnabled(False)
    '''search'''
    def search(self):
        # prevent double-click
        if self.search_worker and self.search_worker.isRunning():
            return
        self.initialize()
        # selected music sources
        music_sources = []
        for cb in self.check_boxes:
            if cb.isChecked():
                music_sources.append(cb.text())
        # keyword
        keyword = self.lineedit_keyword.text()

        # 构建搜索规则 - 根据设置决定是否返回所有品质
        search_rules = {}
        if self.settings.get('return_all_qualities', True):
            # 对于网易云音乐，设置规则来获取多种品质
            for source in music_sources:
                if 'Netease' in source:
                    # 这个规则会在底层被用来决定是否返回所有品质
                    search_rules[source] = {'return_all_qualities': True}

        # disable search button, enable stop button
        self.button_keyword.setEnabled(False)
        self.button_keyword.setText('Searching...')
        self.button_stop.setEnabled(True)
        self.label_status.setText('Searching...')
        # clear table
        self.results_table.setRowCount(0)
        # run search in background thread
        self.search_worker = SearchWorker(music_sources, keyword, search_rules)
        self.search_worker.partial_result.connect(self.on_partial_result)
        self.search_worker.search_finished.connect(self.on_search_finished)
        self.search_worker.finished.connect(lambda: setattr(self, 'music_client', self.search_worker.get_music_client()))
        self.search_worker.start()

    def open_settings(self):
        """打开设置对话框"""
        dialog = SettingsDialog(self.settings, self)
        dialog.exec()
        self.download_dir = self.settings.get('download_dir', os.path.expanduser('~/Downloads'))
        # 更新设置信息
        min_size = self.settings.get('min_file_size_mb', 0)
        return_all_q = self.settings.get('return_all_qualities', True)
        if min_size > 0 or return_all_q:
            print(f"已更新设置 - 最小文件大小: {min_size}MB, 显示所有品质: {return_all_q}")

    def _get_checked_sources(self):
        """获取当前勾选的搜索引擎列表"""
        return [cb.text() for cb in self.check_boxes if cb.isChecked()]

    def closeEvent(self, event):
        """关闭窗口时自动保存设置"""
        self.settings['download_dir'] = self.download_dir
        self.settings['checked_sources'] = self._get_checked_sources()
        save_settings(self.settings)
        super().closeEvent(event)


'''tests'''
if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = MusicdlGUI()
    gui.show()
    sys.exit(app.exec())
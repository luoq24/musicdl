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
    return {'download_dir': os.path.expanduser('~/Downloads'), 'checked_sources': ['NeteaseMusicClient']}


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
        self.resize(450, 150)
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
        save_settings(self.settings)
        self.accept()


# ---------------------------------------------------------------------------
# SearchWorker - runs search in background thread to avoid GUI freeze
# ---------------------------------------------------------------------------
class SearchWorker(QThread):
    search_finished = pyqtSignal(object, str)
    partial_result = pyqtSignal(str, list)  # (source_name, list_of_SongInfo_dicts)

    def __init__(self, music_sources, keyword):
        super().__init__()
        self.music_sources = music_sources
        self.keyword = keyword
        self.music_client = None
        self.stop_event = Event()
        self._accumulated = {}  # {source: [SongInfo, ...]} for dedup

    def stop(self):
        self.stop_event.set()

    def run(self):
        self.music_client = musicdl.MusicClient(music_sources=self.music_sources)
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
        self.src_names = ['QQMusicClient', 'KuwoMusicClient', 'MiguMusicClient', 'QianqianMusicClient', 'KugouMusicClient', 'NeteaseMusicClient']
        self.label_src = QLabel('Search Engine:')
        self.check_boxes = []
        checked_sources = self.settings.get('checked_sources', ['NeteaseMusicClient'])
        for src in self.src_names:
            cb = QCheckBox(src, self)
            cb.setCheckState(Qt.CheckState.Checked if src in checked_sources else Qt.CheckState.Unchecked)
            self.check_boxes.append(cb)
        # input boxes
        self.label_keyword = QLabel('Keywords:')
        self.lineedit_keyword = QLineEdit('尾戒')
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
        for idx, cb in enumerate(self.check_boxes): grid.addWidget(cb, 0, idx+1, 1, 1)
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
    '''initialize'''
    def initialize(self):
        self.search_results = {}
        self.music_records = {}
        self.selected_music_idx = -10000
        self.music_client = None
    '''mouseclick'''
    def mouseclick(self):
        self.context_menu.move(QCursor().pos())
        self.context_menu.show()
    '''download'''
    def download(self):
        self.selected_music_idx = str(self.results_table.selectedItems()[0].row())
        song_info = self.music_records.get(self.selected_music_idx)
        with requests.get(song_info['download_url'], headers=self.music_client.music_clients[song_info['source']].default_download_headers, stream=True, verify=False) as resp:
            if resp.status_code == 200:
                total_size, chunk_size, download_size = int(resp.headers['content-length']), 1024, 0
                os.makedirs(self.download_dir, exist_ok=True)
                download_music_file_path = sanitize_filepath(os.path.join(self.download_dir, song_info['song_name']+'.'+song_info['ext']))
                with open(download_music_file_path, 'wb') as fp:
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        if not chunk: continue
                        fp.write(chunk)
                        download_size += len(chunk)
                        self.bar_download.setValue(int(download_size / total_size * 100))
        QMessageBox().information(self, 'Successful Downloads', f"Finish downloading {song_info['song_name']} by {song_info['singers']}, see {download_music_file_path}")
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

        # showing
        count, row = 0, 0
        for per_source_search_results in self.search_results.values():
            count += len(per_source_search_results)
        self.results_table.setRowCount(count)
        for _, (_, per_source_search_results) in enumerate(self.search_results.items()):
            for _, per_source_search_result in enumerate(per_source_search_results):
                row_data = [
                    str(row),
                    per_source_search_result['singers'],
                    per_source_search_result['song_name'],
                    per_source_search_result['file_size'],
                    per_source_search_result['duration'],
                    per_source_search_result['album'],
                    '',
                    per_source_search_result['source'],
                ]
                for column, item in enumerate(row_data):
                    self.results_table.setItem(row, column, QTableWidgetItem(item))
                    self.results_table.item(row, column).setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                self.music_records.update({str(row): per_source_search_result})
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

    '''handle partial result (incremental display)'''
    def on_partial_result(self, source, song_infos):
        """Called when a source produces new results during search."""
        for song_info in song_infos:
            # Accumulate in search_results
            self.search_results.setdefault(source, []).append(song_info)
            # Add row to table
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            row_data = [
                str(row),
                song_info['singers'],
                song_info['song_name'],
                song_info['file_size'],
                song_info['duration'],
                song_info['album'],
                '',
                song_info['source'],
            ]
            for column, item in enumerate(row_data):
                self.results_table.setItem(row, column, QTableWidgetItem(item))
                self.results_table.item(row, column).setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            self.music_records.update({str(row): song_info})
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
        # disable search button, enable stop button
        self.button_keyword.setEnabled(False)
        self.button_keyword.setText('Searching...')
        self.button_stop.setEnabled(True)
        self.label_status.setText('Searching...')
        # clear table
        self.results_table.setRowCount(0)
        # run search in background thread
        self.search_worker = SearchWorker(music_sources, keyword)
        self.search_worker.partial_result.connect(self.on_partial_result)
        self.search_worker.search_finished.connect(self.on_search_finished)
        self.search_worker.finished.connect(lambda: setattr(self, 'music_client', self.search_worker.get_music_client()))
        self.search_worker.start()

    def open_settings(self):
        """打开设置对话框"""
        dialog = SettingsDialog(self.settings, self)
        dialog.exec()
        self.download_dir = self.settings.get('download_dir', os.path.expanduser('~/Downloads'))

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
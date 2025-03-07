from PySide6.QtGui import QAction

from src.pattern_tracking.logic.video.LiveFeedWrapper import LiveFeedWrapper
from src.pattern_tracking.qt_gui.top_menu_bar.video.NewServerFeedQDialog import NewServerFeedQDialog


class SelectFramesFromServerAction(QAction):

    def __init__(self, live_feed: LiveFeedWrapper):
        super().__init__()
        self._live_feed = live_feed
        self.setText("From live server")
        self.triggered.connect(self._new_live_dialog)

    def _new_live_dialog(self):
        dlg = NewServerFeedQDialog(self._live_feed.get_global_halt_event())
        if dlg.exec():
            feed = dlg.get_connection_result()
            self._live_feed.change_feed(feed)

import time
from threading import Thread, Event

import cv2 as cv

from pattern_tracking.proper.logic.video.AbstractFrameProvider import AbstractFrameProvider


class VideoReader(AbstractFrameProvider):
    """
    Continuously reads frames from a video file
    or from a video feed, and puts them in a readable
    queue, alongside the frame number
    """
    def __init__(self, feed_origin: str | int,
                 is_video: bool,
                 halt_work: Event,
                 max_frames_in_queue: int = 30,
                 loop_video: bool = False):
        super().__init__(halt_work, max_frames_in_queue)

        self._video_feed: cv.VideoCapture = None
        """Video feed"""
        self._initialized = False
        """Set to True when this object has its VideoCapture object initalized properly"""
        self._feed_origin = feed_origin
        """Feed origin input"""
        self._loop = loop_video and is_video
        """Set to True if we want the video to serve forever"""
        self._reset_event = Event()
        """Used to halt this object's work and change its parameters (like the video source)"""
        self._thread: Thread | None = None
        """The thread used to process frames in the background"""

        self._initialize_reader()

        self._frames_shape = self._video_feed.read()[1].shape
        """The shape of the frames taken from the video feed"""

    def start(self):
        """Start a thread, reads & places all grabbed frames in the self._frames_queue attribute"""
        self._thread = Thread(target=self._run)
        self._thread.start()

    def _run(self):
        """
        Thread-safe video reader method
        Opens a video file (or video capture device feed),
        then continuously reads the frames of the video and stores them in a queue

        Data format of the items that are written to the queue are as follows :
        tuple[int, cv.Mat | np.ndarray] | None
        """
        capturing = True
        while capturing:
            frame_id = 0
            while self._video_feed.isOpened() and not self._halt_event.is_set() \
                    and not self._reset_event.is_set():
                ret, frame = self._video_feed.read()
                if not ret:
                    break

                self._frames_queue.put((frame_id, frame))
                frame_id += 1
                if self._is_video:
                    time.sleep(0.05)

            # enable looping if requested, and if not tasked to stop work
            if self._loop and not self._halt_event.is_set() and not self._reset_event.is_set():
                self._video_feed.set(cv.CAP_PROP_POS_MSEC, 0)
                # TODO: check property set correctly with VideoCapture.get(), otherwise re-init VideoCapture object
                # architecture-dependant, see OpenCV's docs about this
            else:
                capturing = False
        self._video_feed.release()

    def get_shape(self):
        return self._frames_shape

    def change_feed(self, feed_origin: int | str, is_video: bool, loop_video: bool = False):
        """
        Changes the video feed used by this reader
        :param feed_origin: ID of the feed to use, or the file name concatenated to the file path
        :param is_video: True if the feed_origin var is a video file
        :param loop_video: Set to True if we should loop the video. The frames number will restart at 0
        :raise IOError if we couldn't open the video or the file
        """
        # Halt the running thread and wait for it to finish
        self._reset_event.set()
        self._thread.join()

        # Change the parameters
        self._feed_origin = feed_origin
        self._initialize_reader()
        self._is_video = is_video
        self._loop = loop_video

        # clear the reset event flag
        self._reset_event.clear()

        # start a new thread
        self._thread = Thread(target=self._run)
        self._thread.start()

    def _initialize_reader(self):
        """Instantiates the cv.VideoCapture object to use"""
        self._video_feed = cv.VideoCapture(self._feed_origin)
        self._initialized = self._video_feed.isOpened()
        if not self._initialized:
            raise IOError("Couldn't open video feed !")

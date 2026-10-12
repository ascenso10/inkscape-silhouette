# (c) 2026 inkscape-silhouette contributors
#
# ProgressWindow.py -- small always-on-top tkinter window that shows the
# current step of a Send to Silhouette job. Inkscape's own "working, please
# wait" dialog cannot be written to by an extension, so we show our own.
#
# There is no mainloop: every call pumps Tk events with update(). If tkinter
# is missing or any Tk call fails (e.g. TclError without a display), the
# window is dropped and every later call is a no-op, so the job continues.


class ProgressWindow:
    def __init__(self):
        self.root = None
        self.status = ""
        try:
            import tkinter
            from tkinter import ttk
            self.root = tkinter.Tk()
            self.root.title("Send to Silhouette")
            self.root.resizable(False, False)
            self.root.attributes("-topmost", True)
            # Ignore the close (X) button: the job cannot be aborted here.
            self.root.protocol("WM_DELETE_WINDOW", lambda: None)
            self.label = ttk.Label(self.root, width=60, anchor="w")
            self.label.pack(fill="x", padx=12, pady=(12, 6))
            self.bar = ttk.Progressbar(self.root, length=400, maximum=100)
            self.bar.pack(fill="x", padx=12, pady=(0, 12))
            self.root.update()
        except Exception:
            self.close()

    def _call(self, func, *args):
        """Run a Tk update, then pump events; drop the window on failure."""
        if self.root is None:
            return
        try:
            func(*args)
            self.root.update()
        except Exception:
            self.close()

    def _set_status(self, text):
        self.status = text
        self.label.configure(text=text)
        self.bar.stop()
        self.bar.configure(mode="indeterminate", value=0)
        self.bar.start(50)

    def _set_progress(self, percent):
        percent = max(0, min(100, percent))
        self.bar.stop()
        self.bar.configure(mode="determinate", value=percent)
        self.label.configure(text="%s %d%%" % (self.status, percent + .5))

    def set_status(self, text):
        """Show a new step; the bar runs in indeterminate mode."""
        self._call(self._set_status, text)

    def set_progress(self, percent):
        """Show percent (0-100) on a determinate bar and in the text line."""
        self._call(self._set_progress, percent)

    def close(self):
        """Destroy the window. Safe to call more than once."""
        root, self.root = self.root, None
        if root is None:
            return
        try:
            root.destroy()
        except Exception:
            pass

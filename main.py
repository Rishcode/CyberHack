import os, sys, subprocess, threading, queue, time
import tkinter as tk
from tkinter import ttk, messagebox

"""
GUI Launcher for Social Media Scrapers (Instagram / Twitter / YouTube)

This tool lets you choose which platform to scrape and set common parameters.
It launches the existing platform scripts in a subprocess with the proper
environment variables. Output is streamed into the GUI.

Scripts expected in same directory:
  - insta_final.py
  - twitter_scrape.py
  
  - youtube_scrape.py
"""

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = {
    'Instagram': os.path.join(BASE_DIR, 'insta_final.py'),
    'Twitter': os.path.join(BASE_DIR, 'twitter_scrape.py'),
    'YouTube': os.path.join(BASE_DIR, 'youtube_scrape.py'),
}

class ScrapeLauncher:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title('Social Media Scraper Launcher')
        self.proc = None
        self.stop_requested = False
        self.queue = queue.Queue()

        # Platform selection
        self.platform_var = tk.StringVar(value='Instagram')
        plat_frame = ttk.LabelFrame(root, text='Platform')
        plat_frame.pack(fill='x', padx=10, pady=6)
        for p in SCRIPTS.keys():
            ttk.Radiobutton(plat_frame, text=p, value=p, variable=self.platform_var, command=self._render_platform_opts).pack(side='left', padx=4, pady=2)

        # Global options
        glob = ttk.LabelFrame(root, text='Global Options')
        glob.pack(fill='x', padx=10, pady=6)
        self.headless_var = tk.BooleanVar(value=False)
        self.attach_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(glob, text='Headless', variable=self.headless_var).pack(side='left', padx=4)
        ttk.Checkbutton(glob, text='Attach Existing Chrome', variable=self.attach_var).pack(side='left', padx=4)

        # Detection / Filtering options
        detect = ttk.LabelFrame(root, text='Detection / Filtering')
        detect.pack(fill='x', padx=10, pady=6)
        self.only_flagged_var = tk.BooleanVar(value=True)
        self.debug_detect_var = tk.BooleanVar(value=False)
        self.use_gemini_var = tk.BooleanVar(value=False)
        self.use_gemini_vision_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(detect, text='Only Flagged', variable=self.only_flagged_var).pack(side='left', padx=4)
        ttk.Checkbutton(detect, text='Debug Detect', variable=self.debug_detect_var).pack(side='left', padx=4)
        ttk.Checkbutton(detect, text='Gemini Text', variable=self.use_gemini_var).pack(side='left', padx=4)
        ttk.Checkbutton(detect, text='Gemini Vision', variable=self.use_gemini_vision_var).pack(side='left', padx=4)
        tag_frame = ttk.Frame(detect)
        tag_frame.pack(fill='x', pady=2)
        ttk.Label(tag_frame, text='Tag Filters:', width=12).pack(side='left')
        self.tag_filters_var = tk.StringVar()
        ttk.Entry(tag_frame, textvariable=self.tag_filters_var, width=50).pack(side='left', fill='x', expand=True)

        # Credentials (optional)
        cred = ttk.LabelFrame(root, text='Credentials (optional)')
        cred.pack(fill='x', padx=10, pady=6)
        self.tw_user = self._labeled_entry(cred, 'Twitter User:', 18)
        self.tw_pass = self._labeled_entry(cred, 'Twitter Pass:', 18, show='*')
        self.ig_user = self._labeled_entry(cred, 'Instagram User:', 18)
        self.ig_pass = self._labeled_entry(cred, 'Instagram Pass:', 18, show='*')

        # Platform specific frame
        self.platform_frame = ttk.LabelFrame(root, text='Platform Parameters')
        self.platform_frame.pack(fill='x', padx=10, pady=6)

        # Action buttons
        act = ttk.Frame(root)
        act.pack(fill='x', padx=10, pady=4)
        self.run_btn = ttk.Button(act, text='Run', command=self.run)
        self.run_btn.pack(side='left')
        self.stop_btn = ttk.Button(act, text='Stop', command=self.stop, state='disabled')
        self.stop_btn.pack(side='left', padx=6)

        # Output log
        out_frame = ttk.LabelFrame(root, text='Output Log')
        out_frame.pack(fill='both', expand=True, padx=10, pady=6)
        self.output = tk.Text(out_frame, height=18, wrap='word')
        self.output.pack(fill='both', expand=True)
        self.output.configure(state='disabled')

        # Finalize
        self._render_platform_opts()
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)
        self._poll_queue()

    # Utility to create labeled entry
    def _labeled_entry(self, parent, label, width=12, **entry_kwargs):
        frame = ttk.Frame(parent)
        frame.pack(fill='x', pady=2)
        ttk.Label(frame, text=label, width=14, anchor='w').pack(side='left')
        var = tk.StringVar()
        ent = ttk.Entry(frame, textvariable=var, width=width, **entry_kwargs)
        ent.pack(side='left', fill='x', expand=True)
        return var

    def _clear_platform_frame(self):
        for w in self.platform_frame.winfo_children():
            w.destroy()

    def _render_platform_opts(self):
        self._clear_platform_frame()
        plat = self.platform_var.get()
        if plat == 'Twitter':
            self.tw_mode = tk.StringVar(value='TIMELINE')
            modes = ttk.Frame(self.platform_frame); modes.pack(fill='x', pady=2)
            ttk.Label(modes, text='Mode:').pack(side='left')
            ttk.Combobox(modes, textvariable=self.tw_mode, values=['TIMELINE','TRENDING','SEARCH'], width=12, state='readonly').pack(side='left', padx=4)
            self.tw_search_via = tk.StringVar(value='AUTO')
            ttk.Label(modes, text='Search Via:').pack(side='left')
            ttk.Combobox(modes, textvariable=self.tw_search_via, values=['AUTO','EXPLORE','DIRECT'], width=10, state='readonly').pack(side='left', padx=4)
            self.tw_search = self._labeled_entry(self.platform_frame, 'Search Terms (,):', 40)
            self.tw_filter = self._labeled_entry(self.platform_frame, 'Filter Terms (,):', 40)
            self.tw_target = self._labeled_entry(self.platform_frame, 'Target Count:', 8)
            self.tw_target.set('30')
        elif plat == 'Instagram':
            self.ig_hashtag = self._labeled_entry(self.platform_frame, 'Hashtag:', 24)
            self.ig_filters = self._labeled_entry(self.platform_frame, 'Filter Terms (,):', 40)
            self.ig_reel_target = self._labeled_entry(self.platform_frame, 'Reel Target:', 8)
            self.ig_reel_target.set('50')
            self.ig_hash_target = self._labeled_entry(self.platform_frame, 'Hashtag Post Target:', 8)
            self.ig_hash_target.set('50')
        else:  # YouTube
            self.yt_terms = self._labeled_entry(self.platform_frame, 'Search Terms (,):', 50)
            self.yt_per_term = self._labeled_entry(self.platform_frame, 'Per Term:', 8)
            self.yt_per_term.set('40')
            self.yt_include_shorts = tk.BooleanVar(value=False)
            ttk.Checkbutton(self.platform_frame, text='Include Shorts', variable=self.yt_include_shorts).pack(anchor='w', pady=2)

    def append_log(self, text):
        self.output.configure(state='normal')
        self.output.insert('end', text)
        self.output.see('end')
        self.output.configure(state='disabled')

    def run(self):
        if self.proc:
            messagebox.showwarning('Busy', 'A scrape process is already running.')
            return
        plat = self.platform_var.get()
        script = SCRIPTS.get(plat)
        if not os.path.isfile(script):
            messagebox.showerror('Error', f'Script not found: {script}')
            return
        env = os.environ.copy()
        # Global flags
        env['HEADLESS'] = '1' if self.headless_var.get() else '0'
        env['ATTACH_EXISTING'] = '1' if self.attach_var.get() else '0'
        # Credentials
        if self.tw_user.get(): env['TWITTER_USERNAME'] = self.tw_user.get()
        if self.tw_pass.get(): env['TWITTER_PASSWORD'] = self.tw_pass.get()
        if self.ig_user.get(): env['INSTA_USERNAME'] = self.ig_user.get()
        if self.ig_pass.get(): env['INSTA_PASSWORD'] = self.ig_pass.get()

        # Platform specific env
        if plat == 'Twitter':
            requested_mode = self.tw_mode.get().upper()
            search_terms_value = self.tw_search.get().strip()
            # If user entered search terms but left mode not SEARCH, auto-upgrade to SEARCH.
            if search_terms_value and requested_mode != 'SEARCH':
                self.append_log('[INFO] Auto-switching Twitter mode to SEARCH due to search terms provided.\n')
                requested_mode = 'SEARCH'
            env['TW_MODE'] = requested_mode
            if search_terms_value:
                env['TW_SEARCH_TERMS'] = search_terms_value
            if self.tw_filter.get().strip():
                env['TW_FILTER_TERMS'] = self.tw_filter.get().strip()
            if self.tw_target.get().isdigit():
                env['TW_POST_TARGET'] = self.tw_target.get().strip()
            env['TW_SEARCH_VIA'] = self.tw_search_via.get().upper()
            # Quick diagnostic dump for Twitter
            diag_keys = ['TW_MODE','TW_SEARCH_TERMS','TW_FILTER_TERMS','TW_POST_TARGET','TW_SEARCH_VIA','ONLY_FLAGGED','DEBUG_DETECT','USE_GEMINI','USE_GEMINI_VISION']
            self.append_log('[ENV] Twitter launch vars:\n')
            for k in diag_keys:
                if k in env:
                    self.append_log(f'  {k}={env[k]}\n')
        elif plat == 'Instagram':
            if self.ig_hashtag.get().strip():
                env['INSTA_HASHTAG'] = self.ig_hashtag.get().strip().lstrip('#')
            if self.ig_filters.get().strip():
                env['INSTA_FILTER_TERMS'] = self.ig_filters.get().strip()
            if self.ig_reel_target.get().isdigit():
                env['REEL_TARGET'] = self.ig_reel_target.get().strip()
            if self.ig_hash_target.get().isdigit():
                env['INSTA_HASHTAG_TARGET'] = self.ig_hash_target.get().strip()
        else:  # YouTube
            if self.yt_terms.get().strip():
                env['YT_SEARCH_TERMS'] = self.yt_terms.get().strip()
            if self.yt_per_term.get().isdigit():
                env['YT_PER_TERM'] = self.yt_per_term.get().strip()
            env['YT_INCLUDE_SHORTS'] = '1' if self.yt_include_shorts.get() else '0'

        # Detection flags applied to all scripts
        env['ONLY_FLAGGED'] = '1' if self.only_flagged_var.get() else '0'
        env['DEBUG_DETECT'] = '1' if self.debug_detect_var.get() else '0'
        env['USE_GEMINI'] = '1' if self.use_gemini_var.get() else '0'
        env['USE_GEMINI_VISION'] = '1' if self.use_gemini_vision_var.get() else '0'
        if self.tag_filters_var.get().strip():
            env['TAG_FILTERS'] = self.tag_filters_var.get().strip()

        self.append_log(f"\n[LAUNCH] {plat} scraper starting...\n")
        try:
            # Use unbuffered mode for immediate stdout visibility
            self.proc = subprocess.Popen([sys.executable, '-u', script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        except Exception as e:
            self.append_log(f"[ERROR] Failed to start process: {e}\n")
            self.proc = None
            return

        self.append_log('[INFO] Environment overrides applied.\n')
        self.run_btn.configure(state='disabled')
        self.stop_btn.configure(state='normal')
        threading.Thread(target=self._reader_thread, daemon=True).start()

    def _reader_thread(self):
        try:
            assert self.proc and self.proc.stdout
            for line in self.proc.stdout:
                self.queue.put(line)
            self.proc.wait()
            rc = self.proc.returncode
            self.queue.put(f"\n[EXIT] Process ended with code {rc}\n")
        except Exception as e:
            self.queue.put(f"[ERROR] Reader thread: {e}\n")
        finally:
            self.queue.put('__PROC_DONE__')

    def _poll_queue(self):
        try:
            while True:
                line = self.queue.get_nowait()
                if line == '__PROC_DONE__':
                    self.proc = None
                    self.run_btn.configure(state='normal')
                    self.stop_btn.configure(state='disabled')
                else:
                    self.append_log(line)
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)

    def stop(self):
        if not self.proc:
            return
        try:
            self.proc.terminate()
            self.append_log('[INFO] Termination signal sent.\n')
        except Exception as e:
            self.append_log(f'[WARN] Could not terminate: {e}\n')

    def on_close(self):
        if self.proc:
            if messagebox.askyesno('Quit', 'A process is running. Terminate and exit?'):
                try:
                    self.proc.terminate()
                except Exception:
                    pass
            else:
                return
        self.root.destroy()


def main():
    root = tk.Tk()
    ScrapeLauncher(root)
    root.mainloop()


if __name__ == '__main__':
    main()

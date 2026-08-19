# -*- coding: utf-8 -*-
"""
AEDT Model Path Re-mapper  (IronPython / run from AEDT: Automation > Run Script)
===========================================================================
What it does
  1. Scans an AEDT project (.aedt) for every referenced model file
     (.sNp, .ibs, .cir, .sp, .spice, .mod, .ami, .dll, .so, .pwl, .tab, .csv ...).
  2. Shows each path with EXISTS / MISSING status and how many times it occurs.
  3. "Auto-match" : pick a search folder; for every (missing) file it finds a
     file with the same name (recursive) and fills it in as the new target.
  4. You may override any target via "Browse...".
  5. "Apply" : (optionally save) -> close ONLY this project -> backup .aedt ->
     replace the exact path literals -> reopen.  Other open projects
     (e.g. running HFSS) are NOT touched.

Why scan the file instead of the COM model API?
  Every model type (Touchstone / IBIS / SPICE / AMI) stores its file path
  differently in the API. Scanning the project text repoints them all in one
  uniform, reliable pass. Replacement is done on the exact stored literal, so
  it is precise and never reformats the rest of the project.

Notes
  * Bytes are preserved exactly (latin-1 round-trip), so no BOM / encoding damage.
  * A timestamped .bak is created next to the .aedt before any change.
"""

import os, re, shutil, datetime, clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
from System.Windows.Forms import (
    Form, Panel, Label, TextBox, Button, CheckBox, DockStyle, AnchorStyles,
    DataGridView, DataGridViewTextBoxColumn, DataGridViewSelectionMode,
    DataGridViewAutoSizeColumnMode, OpenFileDialog, FolderBrowserDialog,
    DialogResult, MessageBox, MessageBoxButtons, MessageBoxIcon, Application,
    BorderStyle, ScrollBars)
from System.Drawing import Size, Point, Color, Font, FontStyle

# model-file extensions we care about
EXT_RE = re.compile(
    r'\.(?:s\d+p|ibs|cir|sp|spice|mod|ami|dll|so|pwl|tab|csv|nport|cosim|ckt|lib|inc)$',
    re.IGNORECASE)
# a quoted token: 'xxx'  or  "xxx"
TOK_RE = re.compile(r"'([^'\r\n]*)'|\"([^\"\r\n]*)\"")


def find_refs(text):
    """Return ordered unique list of file-like paths referenced in text."""
    refs, seen = [], set()
    for m in TOK_RE.finditer(text):
        tok = m.group(1) if m.group(1) is not None else m.group(2)
        if not tok or tok in seen:
            continue
        if not EXT_RE.search(tok):
            continue
        looks_like_path = (re.match(r'^[A-Za-z]:[\\/]', tok)
                           or tok.startswith('\\\\')
                           or '/' in tok or '\\' in tok)
        if looks_like_path:
            seen.add(tok)
            refs.append(tok)
    return refs


def build_index(folder):
    """basename(lower) -> [full paths] for everything under folder."""
    idx = {}
    for root, _dirs, files in os.walk(folder):
        for fn in files:
            idx.setdefault(fn.lower(), []).append(os.path.join(root, fn))
    return idx


class RemapForm(Form):
    def __init__(self):
        self.Text = "AEDT Model Path Re-mapper  -  虎門科技 Jeff Hong 洪敬傑 提供"
        self.Font = Font("Calibri", 9.0)   # 英文/數字介面字型
        self.Size = Size(1040, 620)
        self.MinimumSize = Size(820, 440)
        self.aedt_path = ""
        self.raw_text = ""        # project text (latin-1 decoded)

        # ---- top: project selector ----
        top = Panel(); top.Dock = DockStyle.Top; top.Height = 70
        self.Controls.Add(top)   # dock first, THEN add children (anchors need full width)
        Label(Text="AEDT project (.aedt):", Parent=top,
              Location=Point(10, 12), Size=Size(150, 20))
        self.tb_proj = TextBox(Parent=top, Location=Point(160, 10),
                               Size=Size(620, 22))
        self.tb_proj.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right
        b_active = Button(Text="Use active", Parent=top,
                          Location=Point(790, 8), Size=Size(80, 26))
        b_active.Anchor = AnchorStyles.Top | AnchorStyles.Right
        b_active.Click += self.on_use_active
        b_browse = Button(Text="Browse...", Parent=top,
                          Location=Point(875, 8), Size=Size(80, 26))
        b_browse.Anchor = AnchorStyles.Top | AnchorStyles.Right
        b_browse.Click += self.on_browse_proj
        b_scan = Button(Text="Scan", Parent=top, Location=Point(960, 8),
                        Size=Size(60, 26))
        b_scan.Anchor = AnchorStyles.Top | AnchorStyles.Right
        b_scan.Click += self.on_scan

        Label(Text="Search folder (for Auto-match):", Parent=top,
              Location=Point(10, 42), Size=Size(190, 20))
        self.tb_folder = TextBox(Parent=top, Location=Point(200, 40),
                                 Size=Size(580, 22))
        self.tb_folder.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right
        b_fol = Button(Text="Folder...", Parent=top, Location=Point(790, 38),
                       Size=Size(80, 24))
        b_fol.Anchor = AnchorStyles.Top | AnchorStyles.Right
        b_fol.Click += self.on_browse_folder
        b_auto = Button(Text="Auto-match", Parent=top, Location=Point(875, 38),
                        Size=Size(145, 24))
        b_auto.Anchor = AnchorStyles.Top | AnchorStyles.Right
        b_auto.Click += self.on_auto

        # ---- bottom: actions + log ----
        bottom = Panel(); bottom.Dock = DockStyle.Bottom; bottom.Height = 176
        self.Controls.Add(bottom)   # dock first, THEN add children
        b_rowbrowse = Button(Text="Set selected row -> Browse file...",
                             Parent=bottom, Location=Point(10, 8),
                             Size=Size(230, 26))
        b_rowbrowse.Click += self.on_row_browse
        self.cb_save = CheckBox(Text="Save project before closing",
                                Parent=bottom, Location=Point(260, 12),
                                Size=Size(210, 20)); self.cb_save.Checked = True
        self.cb_reopen = CheckBox(Text="Reopen after fix", Parent=bottom,
                                  Location=Point(470, 12), Size=Size(140, 20))
        self.cb_reopen.Checked = True
        b_apply = Button(Text="APPLY  (backup + fix)", Parent=bottom,
                         Location=Point(640, 6), Size=Size(180, 30))
        b_apply.Click += self.on_apply
        self.log = TextBox(Parent=bottom, Location=Point(10, 44),
                           Size=Size(1000, 96))
        self.log.Multiline = True; self.log.ReadOnly = True
        self.log.ScrollBars = ScrollBars.Vertical
        self.log.Anchor = (AnchorStyles.Top |
                           AnchorStyles.Left | AnchorStyles.Right)

        # ---- center: grid ----
        self.grid = DataGridView()
        self.grid.Dock = DockStyle.Fill
        self.grid.AllowUserToAddRows = False
        self.grid.RowHeadersVisible = False
        self.grid.SelectionMode = DataGridViewSelectionMode.FullRowSelect
        self.grid.MultiSelect = False
        for name, w, ro in [("Status", 90, True), ("Refs", 50, True),
                            ("Original Path", 420, True), ("New Path", 420, False)]:
            c = DataGridViewTextBoxColumn()
            c.HeaderText = name; c.Width = w; c.ReadOnly = ro
            self.grid.Columns.Add(c)
        self.grid.Columns[3].AutoSizeMode = DataGridViewAutoSizeColumnMode.Fill
        self.Controls.Add(self.grid)
        self.grid.BringToFront()

        # try to prefill with active project
        self.on_use_active(None, None)

    # ---------- helpers ----------
    def msg(self, s):
        self.log.AppendText(s + "\r\n")

    def has_desktop(self):
        return 'oDesktop' in globals()

    def active_path(self):
        try:
            p = oDesktop.GetActiveProject()
            return os.path.join(p.GetPath(), p.GetName() + ".aedt")
        except:
            return ""

    # ---------- events ----------
    def on_use_active(self, s, e):
        if self.has_desktop():
            p = self.active_path()
            if p:
                self.tb_proj.Text = p
                if not self.tb_folder.Text:
                    self.tb_folder.Text = os.path.dirname(p)
        else:
            self.msg("(Not running inside AEDT - use Browse to pick a .aedt)")

    def on_browse_proj(self, s, e):
        d = OpenFileDialog(); d.Filter = "AEDT project (*.aedt)|*.aedt"
        if d.ShowDialog() == DialogResult.OK:
            self.tb_proj.Text = d.FileName
            if not self.tb_folder.Text:
                self.tb_folder.Text = os.path.dirname(d.FileName)

    def on_browse_folder(self, s, e):
        d = FolderBrowserDialog()
        if d.ShowDialog() == DialogResult.OK:
            self.tb_folder.Text = d.SelectedPath

    def on_scan(self, s, e):
        path = self.tb_proj.Text.strip().strip('"')
        if not os.path.isfile(path):
            MessageBox.Show("Project file not found:\n" + path)
            return
        self.aedt_path = path
        raw = open(path, 'rb').read()
        self.raw_text = raw.decode('latin-1')
        refs = find_refs(self.raw_text)
        self.grid.Rows.Clear()
        miss = 0
        for r in refs:
            exists = os.path.isfile(r)
            if not exists:
                miss += 1
            occ = self.raw_text.count("'" + r + "'") + self.raw_text.count('"' + r + '"')
            i = self.grid.Rows.Add("OK" if exists else "MISSING", str(occ), r, "")
            self.color_row(i)
        self.msg("Scanned %d model refs (%d missing) in %s"
                 % (len(refs), miss, os.path.basename(path)))

    def color_row(self, i):
        row = self.grid.Rows[i]
        st = row.Cells[0].Value
        if st == "MISSING":
            row.Cells[0].Style.ForeColor = Color.Red
        elif st == "FIXED":
            row.Cells[0].Style.ForeColor = Color.Green
        else:
            row.Cells[0].Style.ForeColor = Color.DarkGreen

    def on_auto(self, s, e):
        folder = self.tb_folder.Text.strip().strip('"')
        if not os.path.isdir(folder):
            MessageBox.Show("Search folder not found:\n" + folder)
            return
        idx = build_index(folder)
        n = 0
        for row in self.grid.Rows:
            orig = row.Cells[2].Value
            if not orig:
                continue
            # only fill rows still missing / empty target
            if row.Cells[0].Value == "OK" and not row.Cells[3].Value:
                continue
            base = os.path.basename(orig.replace('\\', '/')).lower()
            cands = idx.get(base)
            if cands:
                row.Cells[3].Value = cands[0].replace('\\', '/')
                row.Cells[0].Value = "FIXED"
                self.color_row(self.grid.Rows.IndexOf(row))
                n += 1
                if len(cands) > 1:
                    self.msg("  ! %d candidates for %s, picked first"
                             % (len(cands), base))
            else:
                self.msg("  - no match for %s" % base)
        self.msg("Auto-matched %d file(s) from %s" % (n, folder))

    def on_row_browse(self, s, e):
        if self.grid.CurrentRow is None:
            return
        d = OpenFileDialog(); d.Filter = "Model files|*.*"
        if d.ShowDialog() == DialogResult.OK:
            self.grid.CurrentRow.Cells[3].Value = d.FileName.replace('\\', '/')
            self.grid.CurrentRow.Cells[0].Value = "FIXED"
            self.color_row(self.grid.Rows.IndexOf(self.grid.CurrentRow))

    def collect_pairs(self):
        pairs = []
        for row in self.grid.Rows:
            orig = row.Cells[2].Value
            new = row.Cells[3].Value
            if orig and new and new != orig:
                if not os.path.isfile(new):
                    self.msg("  SKIP (new file missing): %s" % new)
                    continue
                pairs.append((orig, new.replace('\\', '/')))
        return pairs

    def on_apply(self, s, e):
        if not self.aedt_path:
            MessageBox.Show("Scan a project first.")
            return
        pairs = self.collect_pairs()
        if not pairs:
            MessageBox.Show("Nothing to apply. Fill in some 'New Path' targets "
                            "(use Auto-match or Browse).")
            return
        if MessageBox.Show("Apply %d path change(s)?\n\nThe project will be "
                           "closed and reopened.\nOther open projects are not "
                           "affected." % len(pairs), "Confirm",
                           MessageBoxButtons.OKCancel) != DialogResult.OK:
            return

        name = os.path.splitext(os.path.basename(self.aedt_path))[0]
        # close just this project
        if self.has_desktop():
            try:
                if name in list(oDesktop.GetProjectList()):
                    if self.cb_save.Checked:
                        try:
                            oDesktop.SetActiveProject(name).Save()
                            self.msg("Saved project before closing.")
                        except Exception as ex:
                            self.msg("Save skipped: %s" % ex)
                    oDesktop.CloseProject(name)
                    self.msg("Closed project '%s'." % name)
            except Exception as ex:
                self.msg("Close warning: %s" % ex)
        # remove stale lock
        lock = self.aedt_path + ".lock"
        if os.path.exists(lock):
            try: os.remove(lock)
            except: pass

        # backup
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = self.aedt_path + "." + stamp + ".bak"
        shutil.copyfile(self.aedt_path, bak)
        self.msg("Backup: %s" % bak)

        # edit (latin-1 lossless round trip)
        raw = open(self.aedt_path, 'rb').read().decode('latin-1')
        for old, new in pairs:
            cnt = raw.count(old)
            raw = raw.replace(old, new)
            self.msg("  %d x  %s\n         -> %s"
                     % (cnt, old, new))
        open(self.aedt_path, 'wb').write(raw.encode('latin-1'))
        remain = raw.count("Cloudia_AEDT")
        self.msg("Done. (info) leftover 'Cloudia_AEDT' tokens = %d" % remain)

        # reopen
        if self.cb_reopen.Checked and self.has_desktop():
            try:
                oDesktop.OpenProject(self.aedt_path)
                self.msg("Reopened. Re-run your analysis now.")
            except Exception as ex:
                self.msg("Reopen failed: %s" % ex)
        MessageBox.Show("Applied %d change(s).\nBackup:\n%s" % (len(pairs), bak),
                        "Finished", MessageBoxButtons.OK, MessageBoxIcon.Information)
        # refresh view
        self.on_scan(None, None)


Application.EnableVisualStyles()
RemapForm().ShowDialog()

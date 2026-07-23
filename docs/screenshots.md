# Screenshots for the README

## The pill (automated — never screenshot it by hand)

```bat
.venv\Scripts\python.exe tools\capture_pill_shots.py
```

renders the real overlay widget offscreen and rewrites the four
`docs/img/pill-*.png` tiles. Rerun it after any change to
`rekounts/ui/overlay.py` so the README never drifts from the app.

## The Hub (manual — takes about two minutes)

The Hub needs the running app (single-instance mutex, real window chrome), so
this part is by hand:

1. **Have something presentable to show.** The Dictation page will be
   published exactly as captured, so either dictate three or four innocuous
   sentences ("Send the roadmap draft to the team before standup." style), or
   temporarily clear anything personal. Check the **Account** display name and
   the visible **microphone name** too — they end up in the shot.
2. Launch the app (`run.bat` or `Rekounts.exe`), tray → **Open Dashboard**.
3. Size the window to roughly **1100 × 720** — big enough to read, small
   enough that GitHub doesn't shrink the text into mush.
4. Capture the window with **Win+Shift+S** (Snipping Tool → Window mode) and
   save as PNG:
   - the **Dictation** page → `docs/img/hub-dictation.png`
   - the **Settings** page → `docs/img/hub-settings.png`
   - optionally **Insights** (after a few days of use it looks great) →
     `docs/img/hub-insights.png`
5. Keep each file under ~400 KB (plain PNG at 100% scale is usually fine).
6. In `README.md`, replace the `TODO(maintainer)` comment in **The Hub**
   section with:

   ```html
   <p align="center">
     <img src="docs/img/hub-dictation.png" width="720"
          alt="The Hub's Dictation page — searchable local history" />
   </p>
   <p align="center">
     <img src="docs/img/hub-settings.png" width="720"
          alt="Settings — a page inside the Hub; every change applies instantly" />
   </p>
   ```

7. Last look before committing: zoom into each PNG once, read every visible
   string, and confirm there is nothing in it you would not put on a billboard.

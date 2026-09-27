# Veyra Desktop

Refine the existing light application shell and dark spatial viewports. The
reference is a calm Apple desktop utility: precise alignment, readable system
type, quiet separators, consistent line icons, and a clear primary action.
This document applies to `src/renderer`; the root design describes Veyra Scope.

- UI type: `-apple-system, BlinkMacSystemFont, Inter, Segoe UI, sans-serif`.
  Monospace is reserved for measured numbers, paths and configuration.
  Type ramp: 9–11px compact viewport labels, 12–15px controls/support text,
  17–21px panel titles and data, 24px page titles, 32–40px empty-state title.
  Responsive intermediate sizes are intentional within this desktop scope.
- Canvas `#f5f5f7`; surface `#ffffff`; sidebar `#ededf0`; ink `#1d1d1f`;
  secondary text `#626269`; separator `#dedee3`; accent `#0069df`.
- Radius: controls 8px, content panels 14px, floating toolbar 12px.
- Spacing: 4, 8, 12, 16, 24, 32, 48px. Group controls by task.
- Icons: existing authored SVG family, 1.7px rounded strokes, 24px viewBox.
- Motion: 140ms control feedback, 200ms view entry, ease-out. No loops except
  a busy indicator; respect reduced motion and reduced transparency.
- Navigation owns five tasks: Overview, Viewer, Session setup, Performance,
  Evaluation. Session setup owns source/configuration; Viewer owns replay.
- Setup: choose format/directory, select sequence, review bounded settings,
  open preview. One primary action. Advanced configuration is disclosed.
- An empty home screen explains the next action instead of presenting missing
  metrics. Active sessions keep the existing three spatial previews.
- Ground truth labels must remain identified as ground truth. Missing values
  remain unavailable. Resource savings never imply map-quality superiority.

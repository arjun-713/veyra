// Judge / Foveation View: one-click Viewer preset that makes the adaptive
// map self-explanatory. Pure state transform — no backend calls, no metrics.

export interface ViewerDisplayState {
  viewMode: string;
  view: string;
  follow: boolean;
  mode: string;
  boundaries: boolean;
  showRings: boolean;
}

export interface JudgeViewSession {
  active: boolean;
  saved: ViewerDisplayState | null;
}

export function judgeViewPreset(current: ViewerDisplayState): ViewerDisplayState {
  return {...current, mode: 'semantic', showRings: true};
}

export function initialJudgeView(): JudgeViewSession {
  return {active: false, saved: null};
}

// Entering captures the current display state once; exiting restores it so
// normal Viewer state is never corrupted by the preset.
export function enterJudgeView(current: ViewerDisplayState, session: JudgeViewSession): {state: ViewerDisplayState; session: JudgeViewSession} {
  const saved = session.saved ?? {...current};
  return {state: judgeViewPreset(current), session: {active: true, saved}};
}

export function exitJudgeView(session: JudgeViewSession, fallback: ViewerDisplayState): {state: ViewerDisplayState; session: JudgeViewSession} {
  return {state: session.saved ? {...session.saved} : {...fallback}, session: initialJudgeView()};
}

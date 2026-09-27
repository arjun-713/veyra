# Desktop refinement implementation plan

Goal: preserve Veyra's spatial dashboard while making setup and navigation clear.
Base: latest main ac3770c plus pre-V2 professor-feedback branch f3a1cb6.

1. Extract setup into `SessionSetup.svelte`; add tested `setup.ts` readiness
   and runtime-state helpers. Validate configuration before resetting a session.
2. Refine `App.svelte`, `Dashboard.svelte`, `Icon.svelte` and desktop CSS:
   one empty-home action, concise navigation, unified surfaces, SVG controls,
   responsive layout, reduced-motion support. Preserve API command ownership.
3. Expose both quality definitions in comparison evidence; document external
   review tasks with accurate implementation/evidence/permission status.
4. Run node tests, Svelte checks, production build and browser flow checks
   (empty, setup, processing, rejection, viewer, evaluation; compact/wide sizes).
   Inspect actual screenshots, then fix findings in one batch.

No mapper-policy, dataset, packaging, presentation or runtime-default changes.
No commit/push requested for this UI task; leave changes reviewable on the branch.

Follow-up requested during execution: capture all workspaces and meaningful
session states into `reports/desktop-ui-review`; support the user's explicit
`wayland-screenshot snap -o` command. Portal enrollment is operator-only; do not
bypass consent or label WebDriver captures as Wayland captures. Audit native
runtime failure handling and platform evidence. Fedora can run locally;
Ubuntu/macOS/Windows require native evidence and functioning Actions billing.

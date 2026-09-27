"""Exercise the real Tauri WebView and runtime through an existing WebDriver session.

Start WebKitWebDriver with TAURI_WEBVIEW_AUTOMATION=true on Linux, create a
session with webkitgtk:browserOptions.binary pointing to Veyra, and pass its ID.
Only OS directory/report pickers are bypassed; discovery, configure,
processing, events, rendering and controls use the production implementation.
"""

import argparse
import base64
import json
import platform
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def capture_screen(output, request, *, wayland):
    """Capture only the enrolled app window; never disguise a portal failure."""
    if wayland:
        subprocess.run(
            ["wayland-screenshot", "snap", "-o", str(output)],
            check=True,
            timeout=15,
            capture_output=True,
            text=True,
        )
    else:
        output.write_bytes(base64.b64decode(request("/screenshot")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--driver", default="http://127.0.0.1:4445")
    parser.add_argument("--session", required=True)
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extended", action="store_true")
    parser.add_argument("--soak-frames", type=int, default=0)
    parser.add_argument(
        "--quality-report",
        type=Path,
        help="Existing measured JSON report for chart review",
    )
    parser.add_argument(
        "--wayland-screenshots",
        action="store_true",
        help="Use wayland-screenshot snap; requires an enrolled Veyra window",
    )
    args = parser.parse_args()
    endpoint = f"{args.driver}/session/{args.session}"

    def request(path, body=None):
        req = urllib.request.Request(
            endpoint + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=150) as response:
                value = json.load(response)["value"]
        except urllib.error.HTTPError as error:
            raise RuntimeError(
                error.read().decode("utf-8", errors="replace")
            ) from error
        if isinstance(value, dict) and "error" in value:
            raise RuntimeError(value)
        return value

    def js(script, *values):
        return request("/execute/sync", {"script": script, "args": list(values)})

    def click(text):
        return js(
            """
            const button=[...document.querySelectorAll('button')]
              .find(b=>b.textContent.trim()===arguments[0] ||
                b.querySelector('strong')?.textContent.trim()===arguments[0] ||
                (b.matches('.layer') && b.textContent.trim().startsWith(arguments[0])));
            if(!button||button.disabled)throw new Error('Control unavailable: '+arguments[0]);
            button.click();return true;
        """,
            text,
        )

    def wait(script, seconds=120, *, allow_error=False):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = js(script)
            if value:
                return value
            error = js("return document.querySelector('[role=alert]')?.textContent")
            if error and not allow_error:
                raise RuntimeError(error)
            time.sleep(0.25)
        raise TimeoutError(js("return document.body.innerText"))

    screenshots = []

    def snapshot(name):
        # Render the changed state before asking the compositor for its frame.
        request(
            "/execute/async",
            {
                "script": "const done=arguments[arguments.length-1];requestAnimationFrame(()=>requestAnimationFrame(()=>done(true)));",
                "args": [],
            },
        )
        capture_screen(
            args.output / f"{name}.png", request, wayland=args.wayland_screenshots
        )
        screenshots.append(
            {
                "file": f"{name}.png",
                "capture": "wayland-screenshot"
                if args.wayland_screenshots
                else "WebKitWebDriver",
                "state": js("return document.querySelector('.status-pill')?.innerText"),
                "screen": js("return document.querySelector('h1')?.innerText"),
            }
        )
        (args.output / "screenshots.json").write_text(
            json.dumps(screenshots, indent=2) + "\n"
        )

    request("/timeouts", {"script": 120000})
    wait("return !!window.veyra", 30)
    args.output.mkdir(parents=True, exist_ok=True)
    snapshot("overview-empty")
    click("Evaluation")
    assert js(
        "return [...document.querySelectorAll('button')].filter(b=>"
        "['Run session validation','Run four-policy benchmark'].includes(b.textContent.trim()))"
        ".every(b=>b.disabled)"
    ), "Evaluation must not start before a session exists"
    snapshot("evaluation-unavailable")
    click("Performance")
    assert js("return document.querySelector('.performance-page')?.clientHeight>200"), (
        "Performance must keep a usable scrolling viewport"
    )
    assert js(
        "return document.querySelector('.performance-page')?.contains(document.querySelector('.health-status'))"
    ), "Health cards must belong to the scrolling page"
    snapshot("performance-waiting")
    js(
        """
        window.__flow={frames:[],telemetry:[],diagnostics:[],statuses:[]};
        window.veyra.onVisualization(f=>window.__flow.frames.push({
          index:f.metadata.index,points:f.metadata.points.count,cells:f.metadata.cells.count,
          bytes:f.payload.byteLength,schema:f.metadata.schema_version}));
        window.veyra.onEvent(e=>{
          if(e.type==='telemetry')window.__flow.telemetry.push(e);
          if(e.type==='diagnostics')window.__flow.diagnostics.push(e);
          if(e.type==='status')window.__flow.statuses.push(e);
        });
        const root=arguments[0];
        window.veyra.chooseDataset=dataset=>window.__TAURI_INTERNALS__.invoke(
          'choose_dataset',{dataset,root});
    """,
        args.dataset_root,
    )
    click("Viewer")
    assert js("return document.querySelector('.play-button').disabled")
    snapshot("viewer-empty")
    click("Session setup")
    snapshot("setup-empty")
    js("""const s=document.querySelector('#dataset-format');s.value='semanticposs';
         s.dispatchEvent(new Event('change',{bubbles:true}));""")
    click("Choose dataset directory…")
    wait("return document.querySelector('#sequence')?.options.length>0")
    snapshot("setup-selected")
    # Reject a malformed draft in the real UI before any session is started.
    js("""document.querySelector('.advanced-setup').open=true;
       const t=document.querySelector('textarea');window.__validDraft=t.value;
       t.value='{invalid';t.dispatchEvent(new Event('input',{bubbles:true}));""")
    snapshot("setup-advanced")
    click("Open dataset & preview")
    wait("return !!document.querySelector('[role=alert]')", allow_error=True)
    assert js("return window.__flow.frames.length===0")
    assert js("return !!document.querySelector('.session-page')")
    snapshot("configuration-error")
    js("""const t=document.querySelector('textarea');t.value=window.__validDraft;
       t.dispatchEvent(new Event('input',{bubbles:true}));
       document.querySelector('[aria-label="Dismiss error"]').click();
       document.querySelector('.advanced-setup').open=false;""")
    js(
        """document.querySelector('.advanced-setup').open=true;
        const t=document.querySelector('textarea'),config=JSON.parse(window.__validDraft);
        config.dataset_root=arguments[0];t.value=JSON.stringify(config);
        t.dispatchEvent(new Event('input',{bubbles:true}));""",
        str(args.output.resolve() / "nonexistent-dataset"),
    )
    click("Open dataset & preview")
    wait("return !!document.querySelector('[role=alert]')", allow_error=True)
    assert js(
        "return document.querySelector('[role=alert]')?.textContent.includes('dataset root does not exist')"
    )
    assert js("return window.__flow.frames.length===0")
    snapshot("dataset-error")
    js("""const t=document.querySelector('textarea');t.value=window.__validDraft;
       t.dispatchEvent(new Event('input',{bubbles:true}));
       document.querySelector('[aria-label="Dismiss error"]').click();
       document.querySelector('.advanced-setup').open=false;""")
    click("Open dataset & preview")
    snapshot("preview-requested")
    wait(
        "return window.__flow.frames.length>0 && !document.querySelector('.map-empty')"
    )
    assert js(
        "return window.__flow.frames[0].points>0 && window.__flow.frames[0].cells>0"
    )
    wait("return !document.querySelector('.play-button').disabled")
    snapshot("viewer-preview")
    js("document.querySelector('.play-button').click();return true")
    wait("return document.querySelector('.status-pill')?.innerText==='Playing'")
    snapshot("viewer-playing")
    js("document.querySelector('.play-button').click();return true")
    wait(
        "return document.querySelector('.status-pill')?.innerText.toLowerCase()==='paused'"
    )
    snapshot("viewer-paused")
    js("""const s=document.querySelector('[aria-label="Playback speed"]');
         s.value='2';s.dispatchEvent(new Event('change',{bubbles:true}));""")
    wait("return !document.querySelector('.play-button').disabled")
    snapshot("viewer-speed")
    click("Elevation")
    wait(
        "return document.querySelector('.layer.selected')?.textContent.includes('Elevation')"
    )
    snapshot("viewer-elevation")
    extended_controls = []
    if args.extended:
        for camera in ["top", "driver", "orbit"]:
            click(camera)
            snapshot(f"viewer-camera-{camera.lower()}")
        click("top")
        click("Map")
        snapshot("viewer-inspection-map")
        js("""const host=document.querySelector('.map-canvas'),r=host.getBoundingClientRect();
            for(let y=1;y<9;y++)for(let x=1;x<9;x++)host.dispatchEvent(new MouseEvent('click',{
                bubbles:true,clientX:r.left+r.width*x/9,clientY:r.top+r.height*y/9}));return true;""")
        inspected = js("return !!document.querySelector('.inspector')")
        if inspected:
            js(
                "document.querySelector('.inspector').scrollIntoView({block:'start'});return true"
            )
            snapshot("viewer-cell-inspector")
            click("Close")
        click("orbit")
        for visibility in ["Raw", "Map", "Both"]:
            click(visibility)
            snapshot(f"viewer-visibility-{visibility.lower()}")
        wait("return !document.querySelector('.play-button').disabled")
        snapshot("viewer-seek")
        for layer in [
            "Ground",
            "Traversability",
            "Motion",
            "LOD resolution",
            "Utility",
            "Semantic",
        ]:
            click(layer)
            wait("return !document.querySelector('.play-button').disabled")
            snapshot(f"viewer-{layer.lower().replace(' ', '-')}")
        js("""const s=document.querySelector('[aria-label="Seek frame"]');
             s.value='0';s.dispatchEvent(new Event('input',{bubbles:true}));
             s.dispatchEvent(new Event('change',{bubbles:true}));""")
        wait("return !document.querySelector('.play-button').disabled")
        for policy in ["uniform40", "distance_lod"]:
            js(
                """const s=document.querySelector('[aria-label="Mapping policy"]');
                 s.value=arguments[0];s.dispatchEvent(new Event('change',{bubbles:true}));""",
                policy,
            )
            wait("return !document.querySelector('.play-button').disabled")
            assert (
                js(
                    "return document.querySelector('[aria-label=\"Mapping policy\"]').value"
                )
                == policy
            )
            snapshot(f"viewer-{policy}")
        assert js("return window.__flow.statuses.at(-1)?.policy") == "distance_lod"
        context_loss_available = js("""const canvas=document.querySelector('.map-canvas canvas');
            const gl=canvas?.getContext('webgl2');window.__contextLoss=gl?.getExtension('WEBGL_lose_context');
            if(!window.__contextLoss)return false;window.__contextLoss.loseContext();return true;""")
        if context_loss_available:
            wait(
                "return document.querySelector('.map-canvas .empty')?.textContent.includes('context lost')"
            )
            snapshot("viewer-webgl-context-lost")
            js("window.__contextLoss.restoreContext();return true")
            wait("return !document.querySelector('.map-canvas .empty')")
            snapshot("viewer-webgl-context-restored")
        click("Performance")
        snapshot("performance-measured")
        for section, name in [
            (".memory-domains", "memory"),
            (".health-status", "health"),
            ("#governor-override", "governor"),
        ]:
            js(
                "document.querySelector(arguments[0]).scrollIntoView({block:'center'});return true",
                section,
            )
            snapshot(f"performance-{name}-detail")
        for governor in ["conserve", "automatic"]:
            js(
                """const s=document.querySelector('#governor-override');
                 s.value=arguments[0];s.dispatchEvent(new Event('change',{bubbles:true}));""",
                governor,
            )
            wait("return !document.querySelector('#governor-override').disabled")
            snapshot(f"performance-governor-{governor}")
        click("Evaluation")
        click("Run session validation")
        snapshot("validation-requested")
        wait(
            "return document.querySelector('.runtime-actions h3')?.innerText.includes('PASS')"
        )
        snapshot("validation-result")
        js("""const s=document.querySelector('#benchmark-count');s.value='1';
             s.dispatchEvent(new Event('input',{bubbles:true}));""")
        click("Run four-policy benchmark")
        snapshot("benchmark-requested")
        wait(
            "return document.querySelector('.page-intro .chip')?.textContent==='COMPLETE'"
        )
        assert js(
            "return document.querySelector('.workspace-scroll').getBoundingClientRect().height>200"
        ), "Report must not collapse benchmark controls"
        snapshot("benchmark-result")
        if args.quality_report:
            # Bypass only the file picker, never invent benchmark observations.
            js(
                "window.veyra.openReport=async()=>arguments[0];return true",
                json.loads(args.quality_report.read_text()),
            )
            click("Open report")
            wait(
                "return document.querySelectorAll('.quality-tradeoff circle').length===8"
            )
            js(
                "document.querySelector('.comparison-evidence').scrollIntoView();return true"
            )
            snapshot("evaluation-policy-comparison")
            js("document.querySelector('.comparison-details').open=true;return true")
            snapshot("evaluation-reconstruction-details")
            js(
                "document.querySelector('.quality-tradeoff').scrollIntoView();return true"
            )
            snapshot("evaluation-accuracy-tradeoff")
            for metric in ["completion", "surfaceChamfer"]:
                js(
                    """const s=document.querySelector('.quality-tradeoff select');
                    s.value=arguments[0];s.dispatchEvent(new Event('change',{bubbles:true}));""",
                    metric,
                )
                snapshot(f"evaluation-{metric}")
        extended_controls = [
            "seek",
            "policy",
            "governor",
            "validation",
            "benchmark",
            "camera",
            "visibility",
        ]
        if context_loss_available:
            extended_controls.append("real WebGL context loss/restoration")
        if inspected:
            extended_controls.append("real cell raycast inspection")
    if args.soak_frames:
        click("Viewer")
        for _ in range(args.soak_frames):
            wait("return !document.querySelector('[title=\"Step frame\"]').disabled")
            before = js("return window.__flow.telemetry.length")
            js("document.querySelector('[title=\"Step frame\"]').click();return true")
            wait(f"return window.__flow.telemetry.length>{before}")
        extended_controls.append("bounded repeated-frame replay")
    click("Overview")
    wait("return document.querySelectorAll('.dashboard-map canvas').length===3")
    assert not js("return !!document.querySelector('.dashboard-map-empty')")
    request(
        "/execute/async",
        {
            "script": "const done=arguments[arguments.length-1];requestAnimationFrame(()=>requestAnimationFrame(()=>done(true)));",
            "args": [],
        },
    )
    args.output.mkdir(parents=True, exist_ok=True)
    canvas = js(
        "return document.querySelector('.dashboard-map canvas').toDataURL('image/png')"
    )
    (args.output / "raw-canvas.png").write_bytes(
        base64.b64decode(canvas.split(",", 1)[1])
    )
    snapshot("dashboard")
    evidence = js("return window.__flow")
    assert evidence["telemetry"], "No real telemetry received"
    assert not evidence["diagnostics"], evidence["diagnostics"]
    click("Session setup")
    snapshot("setup-session-active")
    if args.extended:
        before = js("return window.__flow.frames.length")
        click("Restart runtime")
        wait(f"return window.__flow.frames.length>{before}")
        wait(
            "return [...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Stop session'&&!b.disabled)"
        )
        snapshot("runtime-restarted")
        extended_controls.append("restart")
    click("Stop session")
    wait(
        "return document.querySelector('.notice')?.textContent.includes('Runtime stopped')"
    )
    snapshot("runtime-stopped")
    click("Overview")
    assert js("return !!document.querySelector('.welcome')"), (
        "Stopped overview must offer setup"
    )
    snapshot("overview-stopped")
    evidence["controls"] = [
        "dataset discovery",
        "malformed configuration rejection",
        "invalid dataset rejection",
        "configure",
        "preview",
        "play",
        "pause",
        "speed",
        "layer",
        "dashboard render",
        "stop",
    ] + extended_controls
    evidence["dataset_root"] = args.dataset_root
    repo = Path(__file__).resolve().parents[1]
    evidence["provenance"] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True
        ).strip(),
        "dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=repo, text=True
            ).strip()
        ),
        "capture": "wayland-screenshot"
        if args.wayland_screenshots
        else "WebKitWebDriver",
        "quality_report": str(args.quality_report) if args.quality_report else None,
        "semantic_mode": "dataset ground-truth labels, not neural inference",
    }
    (args.output / "flow.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": "pass",
                "frames": len(evidence["frames"]),
                "evidence": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()

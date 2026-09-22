import Reveal from "../ui/Reveal";
import { RANGE_BANDS } from "../../lib/benchmark-data";
import "./RangeQuality.css";

/* Range quality: error rises predictably as resolution intentionally coarsens. */

const MAX_RMSE = 0.8;

export default function RangeQuality() {
  return (
    <section className="section range-section" aria-labelledby="range-title">
      <div className="wrap">
        <div className="section-head">
          <h2 id="range-title" className="display-lg">
            Error rises predictably
            <br />
            as resolution coarsens.
          </h2>
          <p className="body-lead">
            Range-binned elevation RMSE on the DistanceLOD map. This is the design
            working as intended: cheap far field, exact near field.
          </p>
        </div>
        <Reveal>
          <ol className="range-scale">
            {RANGE_BANDS.map((band) => (
              <li key={band.range}>
                <div className="range-band-head">
                  <p className="measure range-band-range">{band.range}</p>
                  <p className="measure range-band-lod" style={{ color: band.color }}>
                    {band.lod} · {band.resolution}
                  </p>
                </div>
                <div
                  className="range-track"
                  role="img"
                  aria-label={`${band.range}: RMSE ${band.rmse.toFixed(2)} metres at ${band.resolution}`}
                >
                  <span
                    className="range-fill"
                    style={{ width: `${(band.rmse / MAX_RMSE) * 100}%`, background: band.color }}
                  />
                </div>
                <p className="measure range-rmse">{band.rmse.toFixed(2)} m RMSE</p>
              </li>
            ))}
          </ol>
        </Reveal>
      </div>
    </section>
  );
}

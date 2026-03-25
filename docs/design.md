Data Source

Space-Track.org is still the primary source. You'll need a free account. Historical TLE data (pre-2026) comes from bulk yearly TLE archives. For 2026 onward, the gp_history API is queried one day at a time by CREATION_DATE — no per-object (NORAD_CAT_ID) queries. Expect a lot of data — there are now ~11,000+ Starlink satellites, each with TLEs every ~8 hours over years.

Supplementary sources: CelesTrak (celestrak.org) mirrors Space-Track data and is sometimes easier for bulk pulls. Jonathan McDowell's catalog (planet4589.org) is excellent for launch groupings and satellite status tracking.

For the operational/non-operational classification, you'll likely need to infer status from TLE behavior (no altitude changes = non-maneuvering, decaying orbit = deorbiting) since SpaceX doesn't publish official status.

Language & Technology

Python is the right call, and here's why performance-wise:
The heavy computation is orbit propagation between TLE epochs. Use sgp4 (the Python wrapper around the C library — pip install sgp4) which is very fast. The original author used this same approach. For the reference frame correction (removing nodal precession), you'll extract the RAAN and mean anomaly from TLEs and do the co-precessing transform — this is just arithmetic on the Keplerian elements, not full propagation for every frame.
For rendering, you have two realistic paths:

Matplotlib + ffmpeg — This is almost certainly what the original used. It's straightforward: render each frame as a scatter plot, pipe to ffmpeg. The downside is speed. At ~1 frame/second of render time, a 7-year animation at 30fps with daily snapshots could take hours. But it's simple and the output quality is good.

Polars/NumPy for data processing + Matplotlib for rendering — Use Polars instead of Pandas for the data wrangling stage. When you're filtering and interpolating TLEs across thousands of satellites and thousands of timesteps, Polars will be meaningfully faster.
If render time becomes a real bottleneck, consider Cairo or Pillow for frame generation instead of Matplotlib — they're faster for simple scatter plots since you skip all the figure/axes overhead. But start with Matplotlib for correctness, optimize later.

Rough Architecture

The pipeline breaks into three stages:

Stage 1: Data acquisition and storage. Download TLEs from Space-Track, store in a local SQLite database keyed by NORAD ID and epoch. Tag each satellite with its launch group (L1 through L100+). This is a one-time cost, with incremental updates as new TLEs appear.

Stage 2: Preprocessing. For each animation timestep (e.g., every 6–12 hours), find the nearest TLE for each satellite, propagate to the exact timestamp using SGP4, extract the osculating Keplerian elements, and transform into the co-precessing frame. Store the results as a big table: (timestamp, sat_id, launch_group, co_precessing_raan, anomaly, altitude, status). This is the most compute-intensive stage but only needs to run once.

Stage 3: Rendering. Read the preprocessed table, generate one frame per timestep, encode to video. This is embarrassingly parallel if needed.

Performance Estimates

The 7-year span with 3 snapshots/day is ~7,600 frames. With ~7,000 active satellites in recent frames, that's ~50M data points total for preprocessing. SGP4 propagation is fast (~microseconds per call in the C-backed library), so preprocessing should take tens of minutes, not hours. Rendering is the bottleneck — budget 2–4 hours with Matplotlib, or parallelize across cores.

One Practical Tip
Start with just one shell (the original 53° inclination shell at 550 km) to validate your pipeline, since that's what the original visualization shows. Expanding to the full constellation (multiple shells at different inclinations and altitudes) is a later step.
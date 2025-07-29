import sys
import sounddevice as sd

if sys.platform == "linux":
    import pulsectl


def list_playback_streams() -> list[tuple[int, str]]:
    """
    Return [(sink_input_index, pretty_name), ...] for every app playing sound.
    """
    pc = pulsectl.Pulse("audiokeys")
    streams = []
    for s in pc.sink_input_list():
        app_name = s.proplist.get("application.name", "Unknown")
        media_name = s.proplist.get("media.name", "")
        pretty = f"{app_name} — {media_name}"
        streams.append((s.index, pretty))
    pc.close()
    return streams


def route_stream_to_null_sink(sink_input_idx: int, sink_name="audiokeys_null"):
    pc = pulsectl.Pulse("audiokeys")

    # create the sink once
    sinks = [s for s in pc.sink_list() if s.name == sink_name]
    if not sinks:
        mod_idx = pc.module_load("module-null-sink", f"sink_name={sink_name}")
        sinks = [s for s in pc.sink_list() if s.name == sink_name]

    null_sink = sinks[0]
    pc.sink_input_move(sink_input_idx, null_sink.index)
    pc.close()


def ensure_monitor_for_stream(
    sink_input_idx: int,
    null_sink_name: str = "audiokeys_null",
    combine_sink_name: str = "audiokeys_combine",
) -> tuple[int, list[int]]:
    pc = pulsectl.Pulse("audiokeys")
    cleanup: list[int] = []

    # 1️⃣ original hardware sink
    default_sink = pc.server_info().default_sink_name

    # 2️⃣ null sink ---------------------------------------------------------
    sinks = {s.name: s for s in pc.sink_list()}
    if null_sink_name not in sinks:
        mod_null = pc.module_load(
            "module-null-sink",
            f"sink_name={null_sink_name} "
            f"sink_properties=device.description={null_sink_name}",
        )
        cleanup.append(mod_null)
        sinks = {s.name: s for s in pc.sink_list()}

    # 3️⃣ combine sink (= tee) ---------------------------------------------
    if combine_sink_name not in sinks:  # <‑‑ only if missing
        try:
            # PipeWire 0.3.66 exposes this Pulse‑emulation module
            mod_combine = pc.module_load(
                "module-combine-stream",
                # the pulse layer still understands these classic args
                f"sink_name={combine_sink_name} "
                f"slaves={default_sink},{null_sink_name} "
                f"sink_properties=device.description={combine_sink_name}",
            )
        except Exception:
            # Fallback for plain PulseAudio or old PipeWire builds
            mod_combine = pc.module_load(
                "module-combine-sink",
                f"sink_name={combine_sink_name} "
                f"slaves={default_sink},{null_sink_name} "
                f"sink_properties=device.description={combine_sink_name}",
            )

        cleanup.append(mod_combine)
        sinks = {s.name: s for s in pc.sink_list()}

        # 4️⃣ move this app into the tee sink

    pc.sink_input_move(sink_input_idx, sinks[combine_sink_name].index)
    pc.close()

    # ── pick the Pulse device so PortAudio really uses Pulse/PipeWire ──
    for idx, dev in enumerate(sd.query_devices()):
        name = dev["name"].lower()
        if name.startswith("pulse") and dev["max_input_channels"] > 0:
            return idx, cleanup
        if name.startswith("pipewire") and dev["max_input_channels"] > 0:
            pulse_idx = idx  # save as fallback

    # if Pulse wasn’t found but PipeWire was, use that
    if (pulse_idx := locals().get("pulse_idx")) is not None:
        return pulse_idx, cleanup

    # last resort – let PortAudio decide
    return -1, cleanup

// SuperCollider synth definitions for ghsingo's scsynth backend (#35).
//
// Compile with:
//   sclang ghsingo_synthdefs.scd
// which writes .scsyndef files to the same directory. The Go side then
// /d_loadDir's that directory at backend init.
//
// All four defs accept the same control rates ghsingo's backend dial:
//   - freq: root frequency in Hz
//   - amp:  linear amplitude in [0, 1], slewed inside the SynthDef so
//           Go can change it abruptly without clicks

(
  // L0 drone — root sine + sub octave with slow LFO breathing.
  SynthDef(\ghsingo_drone_v1, { |freq=220, amp=0.0, out=0|
    var ampSlewed, lfo, sig;
    ampSlewed = Lag.kr(amp, 0.25);
    lfo = SinOsc.kr(0.1).range(0.7, 1.0);
    sig = (SinOsc.ar(freq) * 0.5 + SinOsc.ar(freq * 0.5) * 0.6) * lfo;
    Out.ar(out, (sig * ampSlewed).dup);
  }).writeDefFile("scsynth/synthdefs");

  // L0.5 tonal bed — band-limited noise centered around freq, used as
  // the synth analogue of the sample-based TonalBedVoice.
  SynthDef(\ghsingo_tonal_v1, { |freq=220, amp=0.0, out=0|
    var ampSlewed, sig;
    ampSlewed = Lag.kr(amp, 0.25);
    sig = BPF.ar(PinkNoise.ar(0.5), freq * 2, 0.4);
    Out.ar(out, (sig * ampSlewed).dup);
  }).writeDefFile("scsynth/synthdefs");

  // L1 bed — pink noise through a fixed lowpass (~600 Hz).
  SynthDef(\ghsingo_bed_v1, { |amp=0.0, out=0|
    var ampSlewed, sig;
    ampSlewed = Lag.kr(amp, 0.25);
    sig = LPF.ar(PinkNoise.ar(0.5), 600);
    Out.ar(out, (sig * ampSlewed).dup);
  }).writeDefFile("scsynth/synthdefs");

  // L2 accent — short Karplus-Strong-ish pluck plus reverb send.
  SynthDef(\ghsingo_accent_v1, { |freq=440, amp=0.7, out=0|
    var burst, sig, env;
    env = EnvGen.kr(Env.perc(0.005, 1.5), doneAction: 2);
    burst = WhiteNoise.ar(0.1) * EnvGen.kr(Env.perc(0.001, 0.01));
    sig = CombC.ar(burst, 0.05, freq.reciprocal, 1.5);
    Out.ar(out, (sig * amp * env).dup);
  }).writeDefFile("scsynth/synthdefs");
)

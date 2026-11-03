import json,sys,time
from faster_whisper import WhisperModel
t=time.time()
m=WhisperModel("small",device="cpu",compute_type="int8",cpu_threads=4)
import wave,numpy as np
wv=wave.open(sys.argv[1]);aud=np.frombuffer(wv.readframes(wv.getnframes()),np.int16).astype(np.float32)/32768
segs,info=m.transcribe(aud,language="pt",word_timestamps=True,vad_filter=False,beam_size=1,condition_on_previous_text=False)
out=[]
for s in segs:
    out.append({"s":s.start,"e":s.end,"t":s.text,"w":[[w.start,w.end,w.word,w.probability] for w in s.words]})
    print(f"{s.start:.1f} {s.text}",flush=True)
json.dump(out,open(sys.argv[2],"w"),ensure_ascii=False)
print("DONE",time.time()-t)

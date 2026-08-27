from faster_whisper import WhisperModel
import gc, threading
m1 = WhisperModel('small', device='cuda', compute_type='float16')
m1 = None
gc.collect()
print('Unloaded')
def load():
    print('Loading CPU')
    WhisperModel('small', device='cpu', compute_type='int8')
    print('Loaded CPU')
t = threading.Thread(target=load)
t.start()
t.join()
print('Done')

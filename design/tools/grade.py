import sys
import numpy as np
from PIL import Image, ImageFilter
src, out_dir = sys.argv[1], sys.argv[2]
rng = np.random.default_rng(7)
im = Image.open(src).convert('RGB')
W, H = im.size
# crop away the left edge (surfers) and a little top/bottom
im = im.crop((int(W*0.09), int(H*0.04), W, int(H*0.93)))
im = im.resize((2200, round(2200*im.height/im.width)), Image.LANCZOS)
a = np.asarray(im).astype(np.float32)/255.0
# faded-film grade: soften saturation, lift blacks, add contrast curve, split-tone
lum = (a*[0.299,0.587,0.114]).sum(-1, keepdims=True)
a = lum + (a-lum)*0.62
a = 0.5 + (a-0.5)*1.12
a = a*0.9 + 0.035
shadow = np.array([0.86,0.98,1.08]); high = np.array([1.06,1.0,0.90])
l2 = (a*[0.299,0.587,0.114]).sum(-1, keepdims=True)
a = a*(shadow*(1-l2) + high*l2)
# darken toward the top so light type sits on the sky
h, w = a.shape[:2]
y = np.linspace(0,1,h)[:,None,None]
a = a*(0.66 + 0.34*np.clip(y*1.5,0,1))
# vignette
xx = np.linspace(-1,1,w)[None,:,None]; yy = np.linspace(-1,1,h)[:,None,None]
a = a*(1 - 0.16*np.clip(xx**2+yy**2-0.35,0,None))
# grain: coarse clumps + fine speckle, stronger in midtones
coarse = rng.normal(0,1,(h//2+1,w//2+1)).astype(np.float32)
coarse = np.asarray(Image.fromarray(coarse).resize((w,h), Image.BICUBIC))
fine = rng.normal(0,1,(h,w)).astype(np.float32)
g = (0.075*coarse + 0.045*fine)[:,:,None]
chroma = rng.normal(0,0.012,(h,w,3)).astype(np.float32)
a = a + g*(0.55+0.9*(1-np.abs(a.mean(-1,keepdims=True)-0.5)*2)) + chroma
a = np.clip(a,0,1)
res = Image.fromarray((a*255).astype(np.uint8))
res.save(out_dir+'/ocean-fence-grain.jpg', quality=80, optimize=True, progressive=True)
res.resize((900, round(900*h/w)), Image.LANCZOS).save(out_dir+'/preview.jpg', quality=85)
# sample palette
def hx(v): return '#%02X%02X%02X' % tuple(int(x*255) for x in v)
print('size', res.size)
print('sky top', hx(a[int(h*0.08):int(h*0.2)].mean((0,1))))
print('sky low', hx(a[int(h*0.3):int(h*0.38)].mean((0,1))))
print('sea', hx(a[int(h*0.44):int(h*0.52), :int(w*0.5)].mean((0,1))))
print('sand', hx(a[int(h*0.8):int(h*0.95), int(w*0.4):int(w*0.8)].mean((0,1))))
# tileable grain overlay
t = rng.normal(0,1,(320,320)).astype(np.float32)
t2 = np.asarray(Image.fromarray(rng.normal(0,1,(160,160)).astype(np.float32)).resize((320,320), Image.BICUBIC))
n = np.clip(0.5 + 0.16*t + 0.2*t2, 0, 1)
rgba = np.zeros((320,320,4), np.uint8)
rgba[...,:3] = np.where(n[...,None]>0.5, 255, 0)
rgba[...,3] = (np.abs(n-0.5)*2*150).astype(np.uint8)
Image.fromarray(rgba).save(out_dir+'/grain-tile.png', optimize=True)

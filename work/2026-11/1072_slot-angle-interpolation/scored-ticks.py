import json
pairs=[l.split() for l in open('build/scratch/pairs.txt')]
base='E:/git/stunt-reel.data/captures/'
for film in ['balloon','traintnl','location']:
    m=json.load(open(f'{base}vault-{film}/frames/meta.json'))
    ticks=sorted({f['film_tick'] for f in m['frames']})
    print(film,len(ticks),'captured ticks')
    for p in pairs:
        if p[1]!=film: continue
        lo,hi=map(int,p[3].split('..'))
        print(' ',p[2],p[3],'dev',p[5],'capture ticks inside:',[t for t in ticks if lo<t<hi])

import json, os, sys
# usage: STUNT_DATA_ROOT=<data root> python scored-ticks.py <census.txt>
pairs=[l.split() for l in open(sys.argv[1])]
base=os.environ['STUNT_DATA_ROOT']+'/captures/'
for film in ['balloon','traintnl','location']:
    m=json.load(open(f'{base}vault-{film}/frames/meta.json'))
    ticks=sorted({f['film_tick'] for f in m['frames']})
    print(film,len(ticks),'captured ticks')
    for p in pairs:
        if p[0]!='PAIR': continue
        if p[1]!=film: continue
        lo,hi=map(int,p[3].split('..'))
        print(' ',p[2],p[3],'dev',p[5],'capture ticks inside:',[t for t in ticks if lo<t<hi])

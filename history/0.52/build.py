#!/usr/bin/env python3
"""Build a hash-locked GTE .04 extension, never flash a connected device."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
STOCK_HASH='28c30d003a8b2a399cf7c019dfc400dcae751c24dc17bc653f325244a3310c09'
APP=0x08020000
EXT=0x08024000

# Geometric XPD = official back focal distance + exit pupil in front of the
# last vertex, at infinity. Zoom profile is explicitly the 70mm end only.
LENSES=[
 dict(name='Biogon 21mm f/2.8',nominal=21,actual=21.5,apex=3,bfd=12.1,pupil_front=10.7,diameter=8.0,menu='F2.8'),
 dict(name='Biogon 28mm f/2.8',nominal=28,actual=28.5,apex=3,bfd=13.1,pupil_front=13.5,diameter=9.5,menu='F4'),
 dict(name='Planar 35mm f/2',nominal=35,actual=35.1,apex=2,bfd=22.6,pupil_front=27.7,diameter=24.9,menu='F5.6'),
 dict(name='Planar 45mm f/2',nominal=45,actual=46.9,apex=2,bfd=28.5,pupil_front=25.0,diameter=27.0,menu='F8'),
 dict(name='Sonnar 90mm f/2.8',nominal=90,actual=90.0,apex=3,bfd=43.7,pupil_front=22.0,diameter=23.5,menu='F11'),
 dict(name='Vario-Sonnar 35-70mm (70mm preset)',nominal=70,actual=68.2,apex=5,bfd=35.9,pupil_front=10.6,diameter=8.0,menu='F16'),
]

def optical(lens):
    # The physical-to-type0 factor 15 follows the EA9 reference's empirical
    # generator. It is a hypothesis for this GTE test build, not calibration.
    # Flat field rows deliberately avoid claiming measured edge vignetting.
    xpd=round((lens['bfd']+lens['pupil_front'])*10)/10
    xs=[round(4500*(7-i)/7) for i in range(8)]
    f=lens['actual']
    axes=[round(384+64*math.log2(f*(f+x/1000)/(x/1000)/1000)) if x else 0x700 for x in xs]
    apertures=[round(i*256/3) for i in range(19)]+[2645]
    ed=struct.pack('<4H',6,1,8,len(apertures))
    for ap in apertures:
        # The last aperture is the conventional terminal marker; the optical
        # values remain monotonic there but it is beyond the physical iris.
        t0n=[round((xpd+4.5)*15)]*6;t0i=[round(xpd*15)]*6
        base=round(lens['apex']*256+ap)
        bellows=round(512*math.log2(1+4.5/f))
        for near,far in [(t0n,t0i),([base+bellows]*6,[base]*6),([base+bellows]*6,[base]*6)]:
            ed+=struct.pack('<5H',1,2,0,0,7)+struct.pack('<12H',*(near+far))
    cs=struct.pack('<4H',1,8,len(apertures),0)+struct.pack('<8H',*axes)+struct.pack('<%dH'%len(apertures),*apertures)
    # LC words 1,2,4 are not fully understood. Match reference structure;
    # word 3 represents this lens's declared maximum aperture.
    lc=struct.pack('<6H',1,848,1008,lens['apex']*256,3195,0)
    chunks=b''.join(tag+struct.pack('<HI',8,len(data))+data for tag,data in [(b'ED',ed),(b'CS',cs),(b'LC',lc)])
    data=b'LF'+struct.pack('<HIII',16,len(chunks)+4,11,0x47544531)+chunks
    assert len(data)%4==0
    word=0
    for w, in struct.iter_unpack('<I',data):word^=w
    return data+struct.pack('<I',word)

def row_b(lens):
    # A flat type-0 row: signed 12-bit mantissa, exponent 2, zero deltas.
    # The A7 IV decoder yields mantissa >> 2; dividing by 256 gives p.
    value=(lens['bfd']+lens['pupil_front'])/lens['actual']
    mantissa=round(value*1024)
    assert 0<mantissa<2048
    return bytes([0x20|(mantissa>>8),mantissa&255,0,0,0,0])

def generate():
    out=['#ifndef GTE_PROFILES_H','#define GTE_PROFILES_H','#include <stdint.h>',
         'struct lens_profile {uint16_t focal_mm10,focal_bcd,file_size,actual_mm10,xpd_mm10;uint8_t row_b[6];const uint8_t *file;};']
    profiles=[]
    for i,lens in enumerate(LENSES):
        data=optical(lens)
        out.append('static const uint8_t optical_%d[] = {%s};'%(i,','.join(hex(b) for b in data)))
        bcd=int(str(lens['nominal']),16)
        profiles.append('{%d,0x%x,%d,%d,%d,{%s},optical_%d}'%(lens['nominal']*10,bcd,len(data),round(lens['actual']*10),round((lens['bfd']+lens['pupil_front'])*10),','.join(hex(b) for b in row_b(lens)),i))
    out+=['static const struct lens_profile profiles[6] = {'+','.join(profiles)+'};','#endif']
    (ROOT/'profiles.h').write_text('\n'.join(out)+'\n')
    meta=[]
    for l in LENSES:
        meta.append({**l,'derived_xpd_mm':round(l['bfd']+l['pupil_front'],1),'file_bytes':len(optical(l))})
    return meta

def elf_read(path):
    b=path.read_bytes()
    if b[:6]!=b'\x7fELF\x01\x01':raise ValueError('expected little-endian ELF32')
    h=struct.unpack_from('<HHIIIIIHHHHHH',b,16)
    phoff,shoff=h[4],h[5];phsize,phnum=h[8],h[9];shsize,shnum=h[10],h[11]
    chunks=[]
    for i in range(phnum):
        p=struct.unpack_from('<8I',b,phoff+i*phsize)
        if p[0]==1 and p[4]:
            if p[3]<EXT:
                if p[3]+p[4]<=EXT and not p[6]&1:continue
                raise ValueError('program segment below extension region')
            chunks.append((p[3],b[p[1]:p[1]+p[4]]))
    if not chunks:raise ValueError('ELF has no loadable program data')
    end=max(addr+len(data) for addr,data in chunks)
    payload=bytearray(b'\xff'*(end-EXT))
    for addr,data in chunks:payload[addr-EXT:addr-EXT+len(data)]=data
    sections=[struct.unpack_from('<10I',b,shoff+i*shsize) for i in range(shnum)]
    symbols={}
    for s in sections:
        if s[1]!=2:continue
        strings=sections[s[6]];st=b[strings[4]:strings[4]+strings[5]]
        for at in range(s[4],s[4]+s[5],s[9]):
            name,value,size,info,other,index=struct.unpack_from('<IIIBBH',b,at)
            if name:
                name=st[name:].split(b'\0')[0].decode()
                symbols[name]=value
    return payload,symbols

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('stock',type=Path);a=ap.parse_args()
    stock=a.stock.read_bytes()
    if hashlib.sha256(stock).hexdigest()!=STOCK_HASH:raise SystemExit('wrong base image; no output written')
    meta=generate();build=ROOT/'build';build.mkdir(exist_ok=True)
    zig=shutil.which('zig')
    # Prefer the pinned Python package when available, for reproducible builds.
    cmd=[sys.executable,'-m','ziglang'] if importlib.util.find_spec('ziglang') else [zig or 'zig']
    cmd+=['cc','-target','thumb-freestanding-eabi','-mcpu=cortex_m4','-mfloat-abi=soft',
          '-Oz','-g','-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-unwind-tables','-fno-asynchronous-unwind-tables',
          '-nostdlib','-Wl,-T,'+str(ROOT/'patch.ld'),'-Wl,--gc-sections','-Wl,-e,patch_reset_entry',
          str(ROOT/'entries.S'),str(ROOT/'patch.c'),'-o',str(build/'patch.elf')]
    subprocess.run(cmd,check=True,cwd=ROOT)
    payload,symbols=elf_read(build/'patch.elf')
    image=bytearray(stock);patches=[]
    def change(off,data,reason):
        before=bytes(image[off:off+len(data)]);image[off:off+len(data)]=data
        patches.append({'file_offset':hex(off),'before':before.hex(),'after':data.hex(),'reason':reason})
    change(20,struct.pack('<I',symbols['patch_reset_entry']|1),'zero extension RAM, then execute original reset')
    for addr,name,expected in [(0x08020b64,'patch_dispatch_entry','f8b5f14847798679'),(0x080221b4,'patch_prepare_entry','38b504460d460b2c')]:
        off=addr-APP+16
        if stock[off:off+8].hex()!=expected:raise ValueError('hook bytes do not match stock image')
        change(off,bytes.fromhex('dff800f0')+struct.pack('<I',symbols[name]|1),name)
    offset=EXT-APP+16
    image.extend(b'\xff'*(offset-len(image)));image.extend(payload)
    if len(image)-16>0x20000:raise ValueError('exceeds original application sector')
    dist=ROOT/'dist';dist.mkdir(exist_ok=True)
    name='GTE_ALL_EXP052.bin';(dist/name).write_bytes(image)
    (dist/'GTE_STOCK_Ver04.bin').write_bytes(stock)
    manifest={'artifact':name,'version':'0.52','status':'experimental_unvalidated_on_hardware','stock_sha256':STOCK_HASH,
              'sha256':hashlib.sha256(image).hexdigest(),'bytes':len(image),'extension_bytes':len(payload),
              'extension_address':hex(EXT),'reserved_ram':['0x20001000','0x20001800'],
              'patches':patches,'symbols':{k:hex(v) for k,v in symbols.items() if k.startswith('patch_')},
              'lenses':meta,'compiler':' '.join(cmd[:3]),'assumptions':['GTE .04 exact stock layout',
              'STM32F4-compatible SRAM covers reserved area','unmeasured mechanical extension 4.5mm',
              'EA9 empirical type0 scale 15; flat vignetting rows','zoom preset corresponds to 70mm only'],
              'claims':{'compiled':True,'hardware_flash_tested':False,'full_area_af_verified':False,
                        'af_accuracy_improved_verified':False,'af_s_supported':False,
                        'two_second_auto_return_implemented':False,'motor_speed_increased':False},
              'changes_from_051':[
                  'Stop and within-tolerance commands execute original physical brake and PID reset',
                  'new motion and reversals use original start state 2; same-direction retargets preserve running state',
                  'native current-position field is populated and motion/status reports are synchronized',
                  'superseded movement events are replaced and native Stop completion parameter is 1'],
              'user_reported_051_hardware_observations':[
                  'camera displayed lens firmware .51 after update',
                  'G35 profile selected; close focus followed by immediate retreat after shutter half-press release'],
              'not_yet_verified':[
                  'whether the observed release retreat came from continued drive, an explicit body request, or another path',
                  'a reliable half-press/release field for a two-second automatic return policy',
                  'actual 0.52 electrical, mechanical, autofocus and shutdown behavior']}
    (dist/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    (build/'symbols.json').write_text(json.dumps(symbols,indent=2)+'\n')
    print(json.dumps({k:manifest[k] for k in ['artifact','bytes','extension_bytes','sha256','status']},indent=2))

if __name__=='__main__':main()

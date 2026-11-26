#!/usr/bin/env python3
"""Execute compiled ARM patch and unmodified stock paths in Unicorn.

Tests do not access a real adapter or prove hardware AF performance.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import struct
import sys
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_MODE_MCLASS,UC_HOOK_MEM_WRITE,UC_HOOK_MEM_READ
from unicorn.arm_const import *
import build

ROOT=Path(__file__).resolve().parent
APP=build.APP
RETURN=0x0803f000
checks=[]

def check(condition,description):
    if not condition:raise AssertionError(description)
    checks.append(description)

def unpack_stock(image):
    # Independent literal/backreference decoder. The previous research tool
    # was also checked by executing the original unpacker on the CPU.
    src,dest,size,fn=struct.unpack_from('<4I',image,0x33f4);at=src-APP+16;out=bytearray()
    while len(out)<size:
        op=image[at];at+=1;n=op&7;r=op>>4
        if n==0:n=image[at];at+=1
        if r==0:r=image[at];at+=1
        out+=image[at:at+n-1];at+=n-1
        if op&8:
            d=image[at];at+=1
            for _ in range(r+2):out.append(out[-d])
        else:out+=bytes(r)
    if len(out)!=size:raise ValueError('bad scatter decode')
    return bytes(out)

def frame(mid,payload=b'',cls=2,seq=0):
    b=bytearray([0xf0,0,0,cls,seq,mid])+payload+b'\0\0\x55'
    struct.pack_into('<H',b,1,len(b));struct.pack_into('<H',b,len(b)-3,sum(b[1:-3])&65535)
    return bytes(b)

class Board:
    def __init__(self,image,stock,index,initialise_lens=True):
        self.u=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
        self.u.mem_map(0x08000000,0x100000);self.u.mem_write(APP,image[16:])
        self.u.mem_write(0x0800c000,bytes([index])+b'\xff'*0x3fff)
        self.u.mem_map(0x20000000,0x4000);self.u.mem_write(0x20000000,unpack_stock(stock))
        self.u.mem_map(0x40000000,0x1000)
        self.u.mem_map(0x40020000,0x4000)
        self.u.mem_map(0x40026000,0x1000)
        self.u.mem_map(0x42408000,0x1000)
        # The unchanged boot enables the Cortex-M4 FPU. The stock brake and
        # PID routines use it; these tests now execute those routines too.
        self.u.reg_write(UC_ARM_REG_C1_C0_2,0x00f00000)
        self.u.reg_write(UC_ARM_REG_FPEXC,0x40000000)
        # The unchanged boot peripheral setup enables DMA transfer-complete
        # interrupts (CR.TCIE). We begin after that setup in these fixtures.
        self.u.mem_write(0x400264b8,struct.pack('<I',0x10))
        self.peripheral_writes=[]
        self.pwm_init_phase=False
        def guard(u,access,address,size,value,_):
            if 0x08000000<=address<0x08100000:raise AssertionError('patch attempted Flash write')
            if 0x40000000<=address<0x60000000:
                self.peripheral_writes.append((address,size,value))
                init_write=self.pwm_init_phase and (
                    0x40000400<=address<0x40000500 or
                    0x40020400<=address<0x40020500 or
                    0x40023800<=address<0x40023900)
                if not init_write and address not in [0x400264c4,0x400264b8,0x400264bc,0x4002640c,0x4240829c,
                                                      0x4000043c,0x40000440]:
                    raise AssertionError(f'unexpected peripheral write {address:#x}')
            elif not 0x20000000<=address<0x20004000:raise AssertionError(f'write outside SRAM {address:#x}')
        self.u.hook_add(UC_HOOK_MEM_WRITE,guard)
        self.call(struct.unpack_from('<I',image,20)[0],until=0x08020268)
        self.w16(0x20000450,500)
        if initialise_lens:self.request(0x0b,b'\0\0')
    def read(self,a,n):return bytes(self.u.mem_read(a,n))
    def r16(self,a):return int.from_bytes(self.read(a,2),'little')
    def r32(self,a):return int.from_bytes(self.read(a,4),'little')
    def w16(self,a,n):self.u.mem_write(a,struct.pack('<H',n))
    def w32(self,a,n):self.u.mem_write(a,struct.pack('<I',n))
    def call(self,addr,args=(),until=RETURN):
        self.u.reg_write(UC_ARM_REG_SP,0x20000d40)
        self.u.reg_write(UC_ARM_REG_LR,RETURN|1)
        for r,v in zip([UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3],args):self.u.reg_write(r,v)
        self.u.emu_start(addr|1,until,count=2000000)
        if self.u.reg_read(UC_ARM_REG_PC)!=until:raise AssertionError(f'CPU budget exhausted at {self.u.reg_read(UC_ARM_REG_PC):#x}')
    def request(self,mid,payload=b'',cls=2,seq=0):
        self.u.mem_write(0x20000590,frame(mid,payload,cls,seq));self.call(0x08020b64)
    def prepare(self,mid,n):
        self.w16(0x2000058a,n)
        self.call(0x080221b4,(mid,n))
        addr=self.r32(0x400264c4);b=self.read(addr,n)
        check(b[0]==0xf0 and b[-1]==0x55 and int.from_bytes(b[1:3],'little')==n,f'{mid:02x}: frame boundary and length')
        check(int.from_bytes(b[-3:-1],'little')==sum(b[1:-3])&65535,f'{mid:02x}: frame checksum')
        return b

def check_optical(data,profile):
    check(data[:4]==b'LF\x10\0','optical LF signature')
    size=16+struct.unpack_from('<I',data,4)[0]
    data=data[:size]
    check(data==build.optical(profile),'emitted optical file equals profile generator')
    words=struct.unpack('<%dI'%(len(data)//4),data);x=0
    for w in words:x^=w
    check(x==0,'optical check word')
    off=16;chunks={}
    while off<len(data)-4:
        tag=data[off:off+2];h,n=struct.unpack_from('<HI',data,off+2)
        check(h==8 and off+h+n<=len(data)-4,'optical chunk bounds')
        chunks[tag]=data[off+h:off+h+n];off+=h+n
    ed=chunks[b'ED'];cs=chunks[b'CS'];nh,nz,nf,na=struct.unpack_from('<4H',ed)
    check((nh,nz,nf,na)==(6,1,8,20),'ED axes and aperture counts')
    check(struct.unpack_from('<3H',cs)==(1,8,20),'CS axes agree with ED')
    pos=8
    for _ in range(na*3):
        a,b,zoom,f0,f1=struct.unpack_from('<5H',ed,pos)
        check((a,b,zoom,f0,f1)==(1,2,0,0,7),'sparse optical block layout')
        pos+=34
    check(pos==len(ed),'all optical ED blocks consumed')

def movement(board):
    board.w16(0x200006c0,100)
    prefix=bytes(13)
    def move(value,mode):board.request(4,prefix+b'\x1d'+struct.pack('<H',value&65535)+bytes([0,mode]),1)
    move(4096+200*4,0);check(board.r16(0x200006c4)==200,'native absolute focus target')
    move(80,4);check(board.r16(0x200006c4)==120,'relative move preserves encoder/protocol scale')
    board.w16(0x2000021a,8)
    move(10,6);check(board.r16(0x200006c4)==120,'defocus move uses declared scale')
    move(0x8000,6);check(board.r16(0x200006c4)==0,'negative defocus saturates at infinity stop')
    move(0x7ffe,6);check(board.r16(0x200006c4)==500,'positive defocus saturates at close stop')
    previous=board.r16(0x200006c4);move(0x7fff,0)
    check(board.r16(0x200006c4)==previous,'no-target sentinel does not move motor')
    board.request(4,prefix+b'\x1c',1);check(board.r16(0x200006c4)==100,'stop holds actual current position')
    b=board.prepare(6,48);check(int.from_bytes(b[8:10],'little')==4496,'native current position report')
    check(int.from_bytes(b[26:28],'little')==4496,'native NOW position agrees with stopped forecast')
    check(int.from_bytes(b[13:15],'little')==4096 and int.from_bytes(b[15:17],'little')==6096,'native travel bounds report')
    rng=random.Random(284)
    for _ in range(100):
        move(rng.randrange(65536),rng.choice([0,1,2,3,4,6]))
        check(0<=board.r16(0x200006c4)<=500,'fuzzed focus target within stock limit')
    old=board.r16(0x200006c4)
    for payload in [prefix+b'\x1d',prefix+b'\x1d\0',prefix+b'\x2f',prefix+b'\x99\0\0']:
        board.request(4,payload,1);check(board.r16(0x200006c4)==old,'truncated/unknown record cannot move motor')
    bad=bytearray(frame(4,prefix+b'\x1c',1));bad[-2]^=1
    board.u.mem_write(0x20000590,bytes(bad));board.call(0x08020b64)
    check(board.r16(0x200006c4)==old,'invalid frame checksum cannot move motor')

def motor_stop_regression(board):
    """Run the unchanged motor state machine, not just packet target writes."""
    prefix=bytes(13)
    def move(count):
        board.request(4,prefix+b'\x1d'+struct.pack('<H',4096+count*4)+b'\0\0',1)
    board.w16(0x200006c0,100)
    board.w32(0x20000448,6500)  # representative existing stock drive ceiling
    board.w32(0x20000424,0)
    move(300)
    check(board.read(0x20000442,1)==b'\x02','motion enters original physical start state')
    board.call(0x08021c94)
    check(board.read(0x20000442,1)==b'\x03','original motor start advances to running state')
    check((board.r32(0x4000043c),board.r32(0x40000440))==(0,6500),
          'original motor start sets physical forward drive channels')
    motion=board.prepare(5,105)
    check(bool(motion[28]&0x40),'normal status reports motor in motion')
    status=board.prepare(6,48)
    check(status[7]==2 and not status[6]&0x80,'native status shows direction and moving state')
    check(int.from_bytes(status[26:28],'little')==4496,'native NOW tracks sampled encoder during motion')
    # Same-direction target updates must not re-enter the motor start/wait.
    move(320)
    check(board.read(0x20000442,1)==b'\x03','same-direction update keeps running state')
    check(board.read(0x200006bc,1)==b'\x01','superseded targets do not accumulate completion events')
    # A reversal must physically brake before selecting the new direction.
    move(40)
    check((board.r32(0x4000043c),board.r32(0x40000440))==(8500,8500),
          'reversal executes unchanged stock H-bridge brake')
    board.call(0x08021c94)
    check((board.r32(0x4000043c),board.r32(0x40000440))==(6500,0),
          'original motor start selects physical reverse drive')
    for a in [0x20000460,0x20000464,0x20000468,0x2000046c]:board.w32(a,0x3f800000)
    board.request(4,prefix+b'\x1c',1)
    check((board.r32(0x4000043c),board.r32(0x40000440))==(8500,8500),
          'Stop physically brakes both motor channels, not only software flags')
    check(all(board.r32(a)==0 for a in [0x20000460,0x20000464,0x20000468,0x2000046c]),
          'Stop clears original PID history and accumulated output')
    check(board.r16(0x200006c4)==100 and board.read(0x20000442,1)==b'\0',
          'Stop holds measured position without a return-to-infinity target')
    stopped=board.prepare(6,48)
    check(stopped[6]&0x80 and stopped[7]==0,'native status acknowledges physical rest')
    check(stopped[8:10]==stopped[26:28]==struct.pack('<H',4496),
          'resting NOW and forecast position fields agree')
    check(not board.prepare(5,105)[28]&0x40,'normal status clears moving flag after Stop')
    # Twenty-five idle state-machine visits with advancing original timers.
    # This is a logical replay, not a physical 2.5-second measurement.
    for i in range(25):
        board.w32(0x20000424,i*10000);board.w32(0x2000042c,i*10000)
        board.call(0x08021c94)
        check(board.r16(0x200006c4)==100 and
              (board.r32(0x4000043c),board.r32(0x40000440))==(8500,8500),
              'idle motor polling cannot restart a stopped drive')
    move(250)
    check(board.read(0x20000442,1)==b'\x02','new focus command responds immediately after idle hold')
    board.call(0x08021c94)
    check((board.r32(0x4000043c),board.r32(0x40000440))==(0,6500),
          'new focus command restarts original forward drive')
    # Already-at-target commands also need physical braking, not a flag only.
    move(102)
    check((board.r32(0x4000043c),board.r32(0x40000440))==(8500,8500),
          'within-stock-tolerance target executes physical brake')
    # Exercise the original event assembly rather than hand-building its tail.
    board.request(4,prefix+b'\x1c',1)
    board.u.mem_write(0x20000441,b'\x06')
    board.call(0x08021a00)
    check(board.r16(0x2000058a)==50,'stock completion assembler emits one Stop event')
    reply=board.prepare(6,50)
    check(reply[45:47]==b'\x1c\x01','native Stop completion uses stopped parameter')
    for count in [0,1,7,8,250,492,493,499,500]:
        board.w16(0x200006c0,count)
        reply=board.prepare(6,48)
        check(int.from_bytes(reply[26:28],'little')==4096+count*4,'native NOW position spans full calibrated travel')
        check(bool(reply[6]&0x10)==(count<=7),'lower-end status reflects physical position')
        check(bool(reply[6]&0x08)==(count>=493),'upper-end status reflects physical position')

def demonstrate_051_failures(stock):
    image=(ROOT/'baseline/GTE_ALL_EXP051.bin').read_bytes()
    check(hashlib.sha256(image).hexdigest()=='d8e587ed33e40c3e806f447e192c08cbb971d6716cbf8504f24bcb17c63cd92d',
          'regression baseline is the exact user-tested 0.51 image')
    b=Board(image,stock,2)
    b.w16(0x200006c0,100);b.w16(0x200006c4,20)
    b.w32(0x4000043c,6500);b.w32(0x40000440,0)
    b.request(4,bytes(13)+b'\x1c',1)
    check((b.r32(0x4000043c),b.r32(0x40000440))==(6500,0),
          '0.51 reproducer: Stop leaves prior physical reverse drive active')
    reply=b.prepare(6,48)
    check(reply[8:10]!=reply[26:28],
          '0.51 reproducer: native NOW is inconsistent with stopped forecast')
    b.request(4,bytes(13)+b'\x1d'+struct.pack('<H',5296)+b'\0\0',1)
    check(b.read(0x20000442,1)==b'\x01',
          '0.51 reproducer: new motion enters wait rather than stock physical start')

def drive_limit_checks(board,stock,index):
    baseline=(ROOT/'baseline/GTE_ALL_EXP052.bin').read_bytes()
    check(hashlib.sha256(baseline).hexdigest()=='fcda2aa0e30f2644ae20700598967fcff25fd032f77b72fd8dfe4cda82c83cd6',
          'drive comparison uses exact user-tested 0.52 image')
    old=Board(baseline,stock,index)
    check(board.r32(0x20000448)==old.r32(0x20000448)==5040,'stock drive ceiling remains 5040 in RAM')
    # Execute the actual stock TIM3 initializer. Only this phase may touch
    # GPIO/RCC/timer configuration. Production motion is still write-guarded.
    board.pwm_init_phase=True
    try: board.call(0x080227a0,(8399,0))
    finally: board.pwm_init_phase=False
    check(board.r16(0x4000042c)==8399,'original PWM initializer yields 8400-count period')
    mode=board.r32(0x4000041c);pol=board.r32(0x40000420)
    check((mode>>4)&7==7 and (mode>>12)&7==7,'stock channels use PWM mode 2')
    check(pol&0x2200==0x2200,'stock PWM channels have inverted polarity')
    old.w16(0x4000042c,8399)
    def configure(b,now=200,to=350,state=5,run=3,direction=None,period=8399,base=5040):
        b.w16(0x200006c0,now);b.w16(0x200006c4,to);b.w16(0x20000450,500)
        b.w32(0x20000448,base);b.w16(0x4000042c,period)
        if direction is None:direction=2 if to>now else 4
        b.u.mem_write(0x20000441,bytes([state,run]));b.u.mem_write(0x200006b4,bytes([direction]))
    def clamp(b,demand):
        b.call(0x08021544,(demand&0xffffffff,));v=b.u.reg_read(UC_ARM_REG_R0)
        return v-(1<<32) if v&(1<<31) else v
    for now,to,cap in [(200,350,7056),(350,200,7056),(200,232,5040),(200,233,5103),
                       (200,248,6048),(200,264,7056),(32,300,5040),(33,300,5103),
                       (48,300,6048),(64,300,7056),(468,200,5040),(467,200,5103),
                       (452,200,6048),(436,200,7056)]:
        for b in [board,old]:configure(b,now,to)
        sign=-1 if to>now else 1
        check(clamp(board,sign*20000)==sign*cap,'40% ceiling tapers at target and mechanical endpoints')
        check(clamp(board,-sign*20000)==clamp(old,-sign*20000),'braking-direction output remains equal to 0.52')
        for demand in [-4500,-2000,0,2000,4500]:
            check(clamp(board,demand)==clamp(old,demand),'unsaturated fine correction is unchanged')
    for state in range(11):
        for run in range(4):
            for b in [board,old]:configure(b,state=state,run=run)
            expected=-7056 if state in (5,6) and run==3 else -5040
            check(clamp(board,-20000)==expected,'boost is limited to running normal-mode AF')
    for period in [0,1000,8398,8400,65535]:
        for b in [board,old]:configure(b,period=period)
        check(clamp(board,-20000)==clamp(old,-20000),'unexpected PWM timing disables boost')
    for now,to,direction in [(0,350,2),(500,100,4),(501,200,4),(200,501,2),(200,350,0),(200,350,4)]:
        for b in [board,old]:configure(b,now,to,direction=direction)
        for demand in [-20000,20000]:
            check(clamp(board,demand)==clamp(old,demand),'invalid/edge/direction states retain baseline clamp')
    for base in [0,1,5000,6500,8400]:
        for b in [board,old]:configure(b,base=base)
        for demand in [-20000,20000]:check(clamp(board,demand)==clamp(old,demand),'nonstandard drive limits are not boosted')
    configure(board)
    check(clamp(board,-(1<<31))==-7056 and clamp(board,(1<<31)-1)==5040,
          'full signed input range saturates without overflow or direction reversal')
    rng=random.Random(53000+index)
    for _ in range(200):
        now,to=rng.randrange(502),rng.randrange(502)
        state,run,direction=rng.randrange(11),rng.randrange(4),rng.choice([0,2,4])
        demand=rng.randrange(-(1<<31),1<<31)
        for b in [board,old]:configure(b,now,to,state,run,direction)
        new,prev=clamp(board,demand),clamp(old,demand)
        check(abs(new)<=7056 and (new==0 or (new<0)==(demand<0)),'fuzzed drive remains bounded and never flips request sign')
        can_boost=(state in (5,6) and run==3 and now<=500 and to<=500 and
                   min(now,500-now)>32 and abs(to-now)>32 and
                   ((to>now and direction==2 and demand<0) or (to<now and direction==4 and demand>0)))
        check((abs(new)>=abs(prev)) if can_boost else new==prev,'fuzzed guard retains baseline output outside intended acceleration band')
    # Exercise the real, unmodified PID -> modified clamp -> original PWM
    # writer. The PID's error sign is CURRENT minus TARGET, not its reverse.
    for now,to,expected_cap in [(200,350,7056),(350,200,7056),(200,220,5040),(20,350,5040),(480,150,5040)]:
        values=[]
        for b in [old,board]:
            configure(b,now,to)
            for a in [0x20000460,0x20000464,0x20000468,0x2000046c]:b.w32(a,0)
            b.call(0x080216ec)
            values.append((b.r32(0x4000043c),b.r32(0x40000440)))
        old_channels,new_channels=values
        check(max(old_channels)==5040 and max(new_channels)==expected_cap,'real PID path uses 0.52 or 40% tapered drive as selected')
        check(new_channels[0]==0 if to>now else new_channels[1]==0,'real PID path keeps the original physical direction')
    # Run the same stop and restart sequence after a boosted PID output.
    configure(board,200,350);board.call(0x080216ec)
    board.request(4,bytes(13)+b'\x1c',1)
    check((board.r32(0x4000043c),board.r32(0x40000440))==(8500,8500),
          '0.52 physical Stop still overrides boosted drive immediately')
    for state in [9,10]:
        configure(board,state=state);check(clamp(board,-20000)==-5040,'initial homing and shutdown retain original drive ceiling')
    # Boosting must not have silently edited gains, baseline cap or timer.
    check([board.r32(a) for a in [0x20000454,0x20000458,0x2000045c]]==
          [old.r32(a) for a in [0x20000454,0x20000458,0x2000045c]],'PID gains remain byte-identical to 0.52')
    check(board.r32(0x20000448)==5040 and board.r16(0x4000042c)==8399,'drive policy leaves baseline cap and PWM period unchanged')

def compare_053_protocol_and_drive(board,stock,index):
    previous=(ROOT/'baseline/GTE_ALL_EXP053.bin').read_bytes()
    check(hashlib.sha256(previous).hexdigest()=='f4d1828e27f09b1b133680d02cbb061c33a1c1f295f9ffd0e74a827cdb458308',
          'comparison baseline is the exact user-tested 0.53 image')
    old=Board(previous,stock,index)
    for now in [0,7,32,100,250,467,500]:
        for b in [old,board]:
            b.w16(0x200006c0,now);b.w16(0x200006c4,now)
            b.u.mem_write(0x200006b4,b'\0')
        for mid,n in [(1,41),(5,105),(6,48),(8,210),(0x28,44),(0x3f,74)]:
            check(board.prepare(mid,n)==old.prepare(mid,n),
                  '0.53 capabilities, status, optical descriptions and lens name preserved')
    a=bytearray(board.prepare(7,43));b=bytearray(old.prepare(7,43))
    check(a[12]==0x55 and b[12]==0x53,'firmware version advances from 0.53 to 0.55')
    for packet in [a,b]:packet[12]=0;packet[-3:-1]=b'\0\0'
    check(a==b,'camera identity differs only in version and corresponding checksum')
    for b in [old,board]:b.request(0x3d,b'\0')
    check(board.prepare(0x3d,72)==old.prepare(0x3d,72),'AF feature declarations match user-tested 0.53')
    def configure(b,now,to,state=5):
        b.w16(0x200006c0,now);b.w16(0x200006c4,to)
        b.w16(0x4000042c,8399);b.w32(0x20000448,5040)
        b.u.mem_write(0x20000441,bytes([state,3]))
        b.u.mem_write(0x200006b4,bytes([2 if to>now else 4]))
    def clamp(b,demand):
        b.call(0x08021544,(demand&0xffffffff,))
        x=b.u.reg_read(UC_ARM_REG_R0)
        return x-(1<<32) if x&(1<<31) else x
    for now,to in [(200,350),(350,200),(200,232),(200,233),(200,248),(33,350),(48,350),(468,200),(467,200)]:
        for b in [old,board]:configure(b,now,to)
        direction=-1 if to>now else 1
        new,prev=clamp(board,direction*20000),clamp(old,direction*20000)
        check(abs(new)>=abs(prev) and abs(new)*100<=abs(prev)*112,
              'extra running drive is at most 12% above the 0.53 limit')
        check(clamp(board,-direction*20000)==clamp(old,-direction*20000),
              'braking limit remains exactly equal to 0.53')
        for demand in [-4500,0,4500]:
            check(clamp(board,demand)==clamp(old,demand),'fine movement matches 0.53')
    for state in [0,2,7,8,9,10]:
        for b in [old,board]:configure(b,200,350,state)
        check(clamp(board,-20000)==clamp(old,-20000),
              'outside normal AF, drive matches user-tested 0.53')

def settled_completion_checks(image,stock,index):
    prior=(ROOT/'baseline/GTE_ALL_EXP054.bin').read_bytes()
    check(hashlib.sha256(prior).hexdigest()=='1cad2387744d792c6aa0a071b94e4f6330306c6fb6ad2f5a2426ed8f13a4352a',
          'settling comparison uses the exact 0.54 image')
    prefix=bytes(13)
    def moving(img=image,state=5):
        b=Board(img,stock,index)
        b.u.mem_write(0x20000441,bytes([state]))
        b.w16(0x200006c0,100);b.w16(0x200006c6,4000)
        b.w16(0x4000042c,8399)
        b.request(4,prefix+b'\x1d'+struct.pack('<H',4896)+b'\0\0',1)
        b.call(0x08021c94)
        check(b.read(0x20000442,1)==b'\x03','settling fixture uses real stock motor start')
        b.w16(0x200006c0,198)
        return b
    def poll(b,tick,dt=0,pos=None):
        if pos is not None:b.w16(0x200006c0,pos)
        b.w32(0x2000043c,tick&0xffffffff)
        if dt:
            for a in [0x20000424,0x2000042c]:b.w32(a,(b.r32(a)+dt)&0xffffffff)
        b.call(0x08021c94)
    def stopped(b):return b.read(0x200006b4,1)==b'\0'
    latencies=[]
    for img in [prior,image]:
        b=moving(img);at=None
        for tick in range(0,10100,100):
            poll(b,tick,100 if tick else 0)
            if stopped(b):at=tick;break
        latencies.append(at)
    check(latencies==[10000,1200],'settled target replay completes at 1200 ticks versus 10000 stock-path ticks')
    b=moving()
    for tick in range(0,1200,100):
        poll(b,tick,100 if tick else 0)
        check(not stopped(b),'stable target is not declared complete before minimum interval')
    poll(b,1200,100)
    check(stopped(b) and b.read(0x20000442,1)==b'\0','settled target clears physical running state')
    check((b.r32(0x4000043c),b.r32(0x40000440))==(8500,8500),'early completion executes the original physical brake')
    check(all(b.r32(a)==0 for a in [0x20000460,0x20000464,0x20000468,0x2000046c]),'early completion clears original PID history')
    check(b.r16(0x200006c4)==200,'early completion preserves the commanded target rather than inventing a return target')
    b.u.mem_write(0x20000441,b'\x06');b.call(0x08021a00)
    reply=b.prepare(6,50)
    check(reply[45:47]==b'\x1d\0' and reply[6]&0x80,'original normal loop reports latest Move completion and rest')
    # Multiple loop calls at the same timestamp are not multiple observations.
    b=moving()
    for _ in range(30):poll(b,0)
    check(not stopped(b),'repeated polls without time progress cannot confirm settling')
    # A single delayed observation must not be interpreted as 12 ms of stability.
    b=moving();poll(b,0);poll(b,1300,1300)
    check(not stopped(b),'observation gap resets rather than falsely completing the move')
    for tick in range(1400,2500,100):poll(b,tick,100)
    check(not stopped(b),'new observation window must run its full interval')
    poll(b,2500,100);check(stopped(b),'new full stable window can complete after a gap')
    # Even when each observation interval is allowed, eight are required.
    b=moving()
    for tick in range(0,2800,400):
        poll(b,tick,400 if tick else 0)
        check(not stopped(b),'elapsed time alone is insufficient without eight observations')
    poll(b,2800,400);check(stopped(b),'sparser observations require a longer actual settling interval')
    # Crossing the target while still travelling must not trigger "done".
    b=moving()
    for i,pos in enumerate([195,197,198,200,201,203,205,207,204,201,199,197,194,190]):
        poll(b,i*100,100 if i else 0,pos)
        check(not stopped(b),'moving through target tolerance is not stable arrival')
    b=moving()
    for i in range(25):
        poll(b,i*100,100 if i else 0,198 if i%2==0 else 202)
        check(not stopped(b),'oscillation inside target tolerance resets the anchor window')
    # Position quantisation of one count is tolerated, but not accumulated creep.
    b=moving()
    for i in range(13):poll(b,i*100,100 if i else 0,198+i%2)
    check(stopped(b),'one-count quantisation can settle inside original target tolerance')
    b=moving()
    for i in range(25):
        poll(b,i*100,100 if i else 0,197+i//6)
        check(not stopped(b),'creeping position cannot accumulate a stationary interval')
    # A replacement target must not inherit the previous target's age.
    b=moving()
    for tick in range(0,1200,100):poll(b,tick,100 if tick else 0)
    b.request(4,prefix+b'\x1d'+struct.pack('<H',4904)+b'\0\0',1)  # target 202, 4 counts away
    poll(b,1100,pos=200)
    for tick in range(1200,2300,100):
        poll(b,tick,100);check(not stopped(b),'retargeting restarts stable-target timing')
    poll(b,2300,100);check(stopped(b),'replacement target completes only after its own stable window')
    # Explicit Stop still has priority, and no automatic return is created.
    b=moving()
    for tick in range(0,1000,100):poll(b,tick,100 if tick else 0)
    b.request(4,prefix+b'\x1c',1)
    check(stopped(b) and (b.r32(0x4000043c),b.r32(0x40000440))==(8500,8500),
          'explicit Stop preempts settling immediately')
    for tick in range(1000,4000,100):poll(b,tick,100)
    check(b.r16(0x200006c4)==198,'stopped target remains held without a timer-driven infinity move')
    b.request(4,prefix+b'\x1d'+struct.pack('<H',5296)+b'\0\0',1)
    poll(b,4000,100)
    check(not stopped(b) and b.read(0x20000442,1)==b'\x03','next focus command restarts normally after settled/explicit stop')
    # New logic must stay out of boot, shutdown and other non-normal sessions.
    for state in [0,1,2,3,4,7,8,9,10]:
        b=moving(state=state)
        for tick in range(0,1600,100):poll(b,tick,100 if tick else 0)
        check(not stopped(b),'early completion is disabled outside normal AF session states')
    # The original failure-to-move watchdog is not bypassed.
    b=moving();b.w16(0x200006c0,150);at=None
    for tick in range(0,10100,100):
        poll(b,tick,100 if tick else 0)
        if stopped(b):at=tick;break
    check(at==10000,'out-of-tolerance stall still follows the original watchdog')
    # Unsigned timer wrap works; a clock reset is treated as a gap.
    b=moving();origin=0xfffffd00
    for i in range(13):poll(b,origin+i*100,100 if i else 0)
    check(stopped(b),'settling interval tolerates normal 32-bit timer wrap')
    b=moving()
    for i in range(12):poll(b,5000+i*100,100 if i else 0)
    poll(b,0,100)
    check(not stopped(b),'timer reset cannot masquerade as completed settling')
    for tick in range(100,1200,100):poll(b,tick,100)
    check(not stopped(b),'clock reset starts a new observation window')
    poll(b,1200,100);check(stopped(b),'settling resumes after a complete post-reset interval')
    return {'prior_054_stop_ticks':latencies[0],'new_055_stop_ticks':latencies[1],
            'nominal_stock_tick_us':10,'physical_motor_or_camera_timing_measured':False}

def dma_cycle(board,mid,n):
    # Execute the original transmitter scheduler and original DMA IRQ, with
    # explicit simulated timer/IRQ registers. This checks its actual 16-bit
    # transfer size and pointer handling; it does not model electrical timing.
    board.w32(0x20000434,1000)
    board.call(0x08021d70)
    check(board.read(0x20000584,1)==b'\x01','stock transmitter entered prepared state')
    board.w16(0x20000586,2);board.call(0x08021d70)
    check(board.r32(0x400264bc)==n,'stock DMA programmed full frame byte count')
    check(board.r32(0x400264c4)==0x20001000,'stock DMA consumes extended transmit buffer')
    check(board.r32(0x400264b8)&1==1,'stock DMA enabled')
    data=board.read(board.r32(0x400264c4),n)
    check(data[5]==mid and data[-1]==0x55,'DMA points to requested complete reply')
    board.w32(0x40026404,0x08000000)
    board.call(0x08020658)
    check(board.read(0x20000584,1)==b'\x03','original DMA interrupt advances transmitter')
    board.call(0x08021d70)
    board.w16(0x20000586,4);board.call(0x08021d70)
    check(board.r16(0x2000058a)==0 and board.read(0x20000585,1)==b'\0','stock transmitter completes and releases busy state')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('stock',type=Path);a=ap.parse_args()
    stock=a.stock.read_bytes();image=(ROOT/'dist/GTE_ALL_EXP055.bin').read_bytes()
    manifest=json.loads((ROOT/'dist/manifest.json').read_text())
    check(hashlib.sha256(stock).hexdigest()==build.STOCK_HASH,'known stock hash')
    check(hashlib.sha256(image).hexdigest()==manifest['sha256'],'output hash matches manifest')
    allowed=set()
    for p in manifest['patches']:
        at=int(p['file_offset'],16);allowed.update(range(at,at+len(bytes.fromhex(p['after']))))
    check(all(a==b or i in allowed for i,(a,b) in enumerate(zip(stock,image))),'base image changes confined to reset vector and four entry hooks')
    check(image[:16]==stock[:16],'vendor update header preserved byte for byte')
    check(image[16:20]==stock[16:20],'initial stack preserved')
    check(image[24:16+0x188]==stock[24:16+0x188],'all other interrupt vectors preserved')
    results=[]
    for i,p in enumerate(build.LENSES):
        early=Board(image,stock,i,False)
        first=early.prepare(1,41)
        early_id=early.prepare(7,43)
        check(early_id[6]==1 and int.from_bytes(early_id[15:17],'little')==0xc563+i,'saved lens selected before the early identity handshake')
        b=Board(image,stock,i)
        m7=b.prepare(7,43);check(m7[6]==1,'native E-mount identity')
        check(m7[12]==0x55,'camera-facing experimental version is 0.55')
        check(int.from_bytes(m7[15:17],'little')==0xc563+i,'per-lens experimental ID')
        m8=b.prepare(8,210);check(m8[15]==1,'native single-position feedback descriptor')
        m5=b.prepare(5,105);check(int.from_bytes(m5[30:32],'little')==p['nominal']*10,'selected lens focal length')
        mantissa=((m5[44]&15)<<8)|m5[45]
        expected=(p['bfd']+p['pupil_front'])/p['actual']
        check(abs(mantissa/1024-expected)<0.002,'per-lens pupil magnification row matches physical baseline')
        caps=b.prepare(1,41)[6:38]
        for mid in [0x3a,0x3b,0x3d]:check(bool(caps[(mid-1)//8]&(1<<((mid-1)%8))),'new file capability declared')
        b.request(0x3d,b'\0');m3d=b.prepare(0x3d,72);check(m3d[6]==1 and m3d[38]==0,'optical file advertised without AF prohibition')
        b.request(0x3a,b'\0\0',3);size=b.prepare(0x3a,32)
        total=int.from_bytes(size[7:9],'little');pages=int.from_bytes(size[11:13],'little')
        check(pages==(total+487)//488,'file size and page count agree')
        all_data=bytearray()
        for page in range(1,pages+1):
            b.request(0x3b,bytes([page,0]),3,17);data=b.prepare(0x3b,500)
            check(data[3]==3 and data[7:9]==bytes([page,0]),'paged response class and page echo')
            all_data+=data[9:497]
            check(b.r16(0x2000058a)==500,'500-byte frame did not overwrite stock TX state')
        check_optical(bytes(all_data[:total]),p)
        # After long packets, the unmodified short-packet fallback must switch
        # DMA back to the original buffer without retaining its old pointer.
        b.prepare(0x0c,10);check(b.r32(0x400264c4)==0x20000484,'stock DMA fallback restored after file transfer')
        movement(b)
        motor_stop_regression(b)
        drive_limit_checks(Board(image,stock,i),stock,i)
        compare_053_protocol_and_drive(Board(image,stock,i),stock,i)
        settling=settled_completion_checks(image,stock,i)
        bus=Board(image,stock,i)
        bus.request(0x3a,b'\0\0',3);dma_cycle(bus,0x3a,32)
        bus.request(0x3b,b'\x01\0',3);dma_cycle(bus,0x3b,500)
        results.append({'lens':p['name'],'index':i,'file_pages':pages,'file_bytes':total,'checks':'PASS'})
    demonstrate_051_failures(stock)
    report={'status':'PASS','check_count':len(checks),'lenses':results,'image_sha256':hashlib.sha256(image).hexdigest(),
            'settled_target_replay':settling,
            'drive_policy':{'stock_ceiling':5040,'maximum_boosted_ceiling':7056,
                            'previous_053_ceiling':6300,'ceiling_increase_vs_053_percent':12,
                            'relative_ceiling_increase_percent':40,'pwm_period_counts':8400,
                            'actual_motor_speed_gain_measured':False},
            'video_af':{'native_identity_retained':True,'new_video_handlers_added':False,
                        'sampled_descriptors_and_static_status_match_053':True,'recording_tested':False,
                        'shared_movement_completion_timing_changes':True},
            'regressions':{'051_stop_leaves_physical_drive_active':'REPRODUCED',
                           '051_native_position_inconsistent':'REPRODUCED',
                           '051_incorrect_motor_start_state':'REPRODUCED',
                           '052_original_motor_start_stop_and_direction':'PASS'},
            'hardware_tested':False,'limits':['peripheral timing and DMA transfers are not modelled',
            'no camera has consumed these replies','optical scale and mechanical travel remain uncalibrated',
            'AF-S and zoom position detection are not implemented']}
    (ROOT/'dist/verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()

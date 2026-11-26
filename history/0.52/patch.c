/* Experimental SHOTEN GTE .04 extension.  Not hardware-validated.
 * The stock calibration, PWM, current position feedback and hard limits are
 * retained. This module changes E-mount protocol and lens descriptions.
 * Fixed addresses are accepted only for the exact stock SHA-256 in build.py.
 */
#include <stdint.h>
#include <stddef.h>
#include "profiles.h"

#define B(a) (*(volatile uint8_t *)(uintptr_t)(a))
#define H(a) (*(volatile uint16_t *)(uintptr_t)(a))
#define W(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define PTR(a) ((volatile uint8_t *)(uintptr_t)(a))
#define RX PTR(0x20000590)
#define TX PTR(0x20000484)
#define BIG PTR(0x20001000)
#define DMA_M0AR W(0x400264c4)
#define CTX ((volatile struct context *)(uintptr_t)0x20001200)
#define MAGIC 0x47544531u
#define STOCK_QUEUE ((void (*)(uint32_t,uint32_t,uint32_t,uint32_t))0x0802233du)
#define STOCK_MOTOR_STOP ((void (*)(void))0x08022089u)

struct context {
    uint32_t magic;
    uint8_t file_selected, file_p0, file_p1, file_seq;
    uint8_t profile_seen, rx_invalid, reserved[2];
    uint32_t file_requests, focus_commands, unsupported_commands;
};
_Static_assert(sizeof(struct context) <= 0x100, "context exceeds reservation");

static unsigned get16(const volatile uint8_t *p) { return p[0] | (unsigned)p[1]<<8; }
static void put16(volatile uint8_t *p,unsigned x) {p[0]=(uint8_t)x;p[1]=(uint8_t)(x>>8);}
static void zero(volatile uint8_t *p,unsigned n) {while(n--)*p++=0;}
static void copy(volatile uint8_t *d,const volatile uint8_t *s,unsigned n) {while(n--)*d++=*s++;}

static void ensure(void) {
    if(CTX->magic == MAGIC) return;
    zero(PTR(0x20001200),sizeof(struct context));
    unsigned idx=3;
    for(unsigned i=0;i<0x4000;i++) {
        unsigned v=B(0x0800c000+i);
        if(v==255)break;
        if(v<6)idx=v;
    }
    B(0x20000422)=(uint8_t)idx;
    CTX->profile_seen=(uint8_t)idx;
    CTX->magic=MAGIC;
}
static unsigned index_now(void) {ensure();unsigned x=B(0x20000422);return x<6?x:3;}
static const struct lens_profile *profile(void) {return &profiles[index_now()];}

static unsigned checksum(const volatile uint8_t *p,unsigned n) {
    unsigned sum=0;for(unsigned i=1;i+3<n;i++)sum+=p[i];return sum&65535;
}
static void finish(volatile uint8_t *p,unsigned n) {
    p[0]=0xf0;put16(p+1,n);put16(p+n-3,checksum(p,n));p[n-1]=0x55;
}
static int rx_valid(unsigned *n) {
    *n=get16(RX+1);
    if(RX[0]!=0xf0 || *n<9 || *n>256 || RX[*n-1]!=0x55) return 0;
    return get16(RX+*n-3)==checksum(RX,*n);
}

/* All positions remain in the stock protocol's 0x1000 + encoder*4 scale.
 * Mechanical travel in um is an explicitly documented unmeasured estimate.
 */
static unsigned limit(void) {unsigned x=H(0x20000450);return x<=500?x:500;}
static unsigned current(void) {unsigned x=H(0x200006c0),m=limit();return x<m?x:m;}
static unsigned distance_code(unsigned count) {
    if(!count)return 0x700;
    const struct lens_profile *p=profile();
    unsigned m=limit();if(!m)return 0x700;
    unsigned x=(count*4500u)/m;if(!x)return 0x700;
    unsigned f=p->focal_mm10*100u;
    /* distance in millimetres, using a rigid lens at infinity. */
    unsigned mm=(p->focal_mm10*(f+x))/(10u*x);
    unsigned e=0,v=mm;while(v>1){v>>=1;e++;}
    unsigned q=mm<<(30-e),frac=0;
    for(unsigned i=0;i<6;i++) {
        uint64_t sq=(uint64_t)q*q;q=(unsigned)(sq>>30);frac<<=1;
        if(sq & ((uint64_t)1<<61)){q>>=1;frac|=1;}
    }
    int result=384+(int)(e*64+frac)-638;
    return result<0?0:result>0x700?0x700:(unsigned)result;
}
static unsigned count_for_distance(unsigned code) {
    if(code>=0x700)return 0;
    unsigned lo=0,hi=limit();
    while(lo<hi){unsigned mid=(lo+hi)/2;if(distance_code(mid)>code)lo=mid+1;else hi=mid;}
    return lo;
}

static void event(unsigned tag) {
    /* A newer target replaces the running move. Do not eventually acknowledge
     * every intermediate target as though it had been physically reached. */
    B(0x200006b7)=(uint8_t)tag;
    B(0x200006bc)=1;
}
static void target(int next,unsigned tag) {
    unsigned now=current(),m=limit();
    if(next<0)next=0;if((unsigned)next>m)next=(int)m;
    event(tag);
    H(0x200006c4)=(uint16_t)next;
    int err=next-(int)now;
    if(err<=3 && err>=-3) {
        /* Changing a software flag does not change the H-bridge outputs.
         * The stock stop brakes both PWM channels and clears PID history. */
        STOCK_MOTOR_STOP();
        B(0x200006b4)=0;B(0x200006b6)=1;B(0x20000442)=0;
    } else {
        unsigned dir=err>0?2:4;
        unsigned active=B(0x20000442),old_dir=B(0x200006b4);
        if(old_dir!=dir || (active!=2 && active!=3)) {
            /* The stock state 2 selects the physical direction and resets
             * its movement timers. State 1 is only a wait, not a start. */
            STOCK_MOTOR_STOP();
            B(0x20000442)=2;
        }
        B(0x200006b4)=(uint8_t)dir;B(0x200006b6)=0;
        W(0x20000430)=10000; /* same movement watchdog interval as stock */
    }
}

static void apply_rows(volatile uint8_t *f,unsigned a,unsigned b) {
    const struct lens_profile *p=profile();
    unsigned m=limit(),ext=m?(current()*4500u)/m:0;
    unsigned focal=p->actual_mm10*100u;
    unsigned mantissa=((p->xpd_mm10*100u+ext)*1024u+focal/2)/focal;
    if(mantissa>2047)mantissa=2047;
    zero(f+a,6);zero(f+b,6);
    f[b]=(uint8_t)(0x20u|(mantissa>>8));f[b+1]=(uint8_t)mantissa;
}
static void capability(void) {
    /* Advertise only implemented channels. Record IDs share this bitmap. */
    volatile uint8_t *p=PTR(0x2000001e);zero(p,32);
    const uint8_t ids[]={1,2,3,4,5,6,7,8,9,10,11,12,13,16,22,25,27,28,29,40,58,59,61,63};
    for(unsigned i=0;i<sizeof(ids);i++){unsigned n=ids[i]-1;p[n/8]|=1u<<(n%8);}
}
static void descriptions(void) {
    const struct lens_profile *p=profile();
    capability();
    volatile uint8_t *m7=PTR(0x20000041);
    m7[6]=1; m7[12]=0x52; /* experimental version 0.52, not an official .05 */
    put16(m7+15,0xc563u+index_now());
    volatile uint8_t *m8=PTR(0x20000081);
    m8[15]=1; /* native single-position feedback; no eight-sample trace claim */
    m8[19]=0xa1; /* full-frame, existing 105-byte normal status */
    m8[38]&=(uint8_t)~1u;
    volatile uint8_t *m5=PTR(0x2000019e);
    m5[65]&=(uint8_t)~3u;
    apply_rows(m5,38,44);apply_rows(PTR(0x20000247),17,23);
    /* Keep EXIF and IBIS nominal focal lengths for primes; zoom is explicitly
     * a manual 70mm preset, since the adapter cannot read zoom position. */
    put16(m5+30,p->focal_mm10);put16(m5+32,p->focal_mm10);
    put16(PTR(0x20000251),p->focal_mm10);put16(PTR(0x20000253),p->focal_mm10);
    put16(m8+22,p->focal_bcd);
    if(index_now()==5) { /* actual maximum aperture at the telephoto preset */
        put16(m8+6,0x1500);m8[26]=0x56;
        m5[50]=m5[52]=m5[57]=0x30;
    }
}

/* Called instead of the stock input dispatcher; 0 delegates to its unchanged
 * first instructions, 1 consumes this input. The stock RX buffer is reused.
 */
int patch_dispatch(void) {
    ensure();unsigned n;
    if(!rx_valid(&n)){CTX->rx_invalid++;return 1;}
    unsigned id=RX[5];
    if(id==0x3d){descriptions();STOCK_QUEUE(0x3d,0,72,20);return 1;}
    if(id==0x3a || id==0x3b) {
        if(RX[3]!=3 || n<10)return 1;
        CTX->file_p0=RX[6];CTX->file_p1=n>10?RX[7]:0;CTX->file_seq=RX[4];
        if(id==0x3a)CTX->file_selected=(RX[6]==0);
        CTX->file_requests++;
        STOCK_QUEUE(id,0,id==0x3a?32:500,20);return 1;
    }
    if(id!=4)return 0;
    if(n<22)return 1;
    unsigned end=n-3,off=19;
    while(off<end) {
        unsigned tag=RX[off];
        if(tag==0x2f){if(end-off<3)break;off+=3;continue;}
        if(tag==0x1c){target((int)current(),0x1c);off++;continue;}
        if(tag!=0x1d || end-off<5){CTX->unsupported_commands++;break;}
        unsigned operand=get16(RX+off+1),mode=RX[off+4]&7,now=current();int next;
        if(operand==0x7fff){off+=5;continue;}
        if(mode==3)next=(int)count_for_distance(operand);
        else if(mode==4)next=(int)now+(int16_t)operand/4;
        else if(mode==6) {
            unsigned scale=H(0x2000021a);if(!scale || scale>1024)scale=8;
            next=(int)now+((int32_t)(int16_t)operand*(int)scale)/4;
        } else if(mode<=2)next=((int)operand-4096)/4;
        else {CTX->unsupported_commands++;break;}
        target(next,0x1d);CTX->focus_commands++;off+=5;
    }
    return 1;
}

static unsigned template_address(unsigned id) {
    switch(id) {
    case 1:return 0x20000018;case 5:return 0x2000019e;case 6:return 0x20000207;
    case 7:return 0x20000041;case 8:return 0x20000081;case 0x28:return 0x20000247;
    case 0x3f:return 0x20000290;default:return 0;
    }
}
int patch_prepare(unsigned id,unsigned n) {
    ensure();descriptions();
    unsigned src=template_address(id);
    if(!src && id!=0x3d && id!=0x3a && id!=0x3b) {DMA_M0AR=0x20000484;return 0;}
    if(n<9 || n>500) {H(0x2000058a)=0;return 1;}
    zero(BIG,500);
    if(src) {
        if(n>256){H(0x2000058a)=0;return 1;}
        copy(BIG,PTR(src),n);
        if(id==5) {
            unsigned d=distance_code(current());put16(BIG+26,d);
            BIG[28]=(uint8_t)((BIG[28]&~0x40u)|0x80u|
                             (B(0x200006b4)?0x40u:0u));
        }
        if(id==6) {
            unsigned now=current(),m=limit(),pos=4096+now*4;
            unsigned dir=B(0x200006b4);
            /* Native NOW and one-frame-ahead fields must agree at rest.
             * No measured velocity predictor exists here: report the sampled
             * position in both, instead of leaving native NOW frozen at zero. */
            put16(BIG+8,pos);put16(BIG+26,pos);
            put16(BIG+11,4096);put16(BIG+13,4096);put16(BIG+15,4096+m*4);
            BIG[7]=(uint8_t)dir;
            BIG[6]=(uint8_t)(0x02u|(dir?0u:0x80u));
            if(now<=7)BIG[6]|=0x10;
            if(m-now<=7)BIG[6]|=0x08;
            /* The original event assembler uses an ordinal parameter. A
             * native Stop completion carries 1, not that ordinal zero. */
            for(unsigned at=45;at+3<n;at+=2)
                if(BIG[at]==0x1c)BIG[at+1]=1;
        }
    } else if(id==0x3d) {
        BIG[3]=2;BIG[4]=0;BIG[5]=0x3d;BIG[6]=1;
    } else if(id==0x3a) {
        BIG[3]=3;BIG[4]=0;BIG[5]=0x3a;
        if(CTX->file_selected) {
            unsigned total=profile()->file_size+16u;
            put16(BIG+7,total);put16(BIG+11,(total+487)/488);
        }
    } else {
        BIG[3]=3;BIG[4]=CTX->file_seq;BIG[5]=0x3b;
        const struct lens_profile *p=profile();unsigned page=CTX->file_p0;
        unsigned pages=(p->file_size+16u+487)/488;
        if(!page)page=1;if(page>pages)page=pages;
        BIG[6]=0;BIG[7]=CTX->file_p0;BIG[8]=CTX->file_p1;
        unsigned start=(page-1)*488u;
        if(CTX->file_selected && start<p->file_size) {
            unsigned count=p->file_size-start;if(count>488)count=488;
            copy(BIG+9,p->file+start,count);
        }
    }
    finish(BIG,n);DMA_M0AR=0x20001000;return 1;
}

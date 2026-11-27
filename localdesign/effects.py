"""Visual effects for screens: animated GPU shader backgrounds and ASCII-art animations. All original, MIT, offline.

Markup only — the runtime does the rest:
  <section data-ld-shader="aurora" data-ld-colors="#070b18,#22d3a6,#8b5cf6" data-ld-speed="0.6">…content stays on top…</section>
  <div data-ld-ascii="orb" style="min-height:240px;color:#22c55e"></div>
  <section data-ld-shader="custom"><script type="x-shader/x-fragment">void mainImage(out vec4 o, in vec2 p){…}</script></section>

Shaders use Shadertoy's conventions (mainImage, iResolution, iTime, iTimeDelta, iFrame, iMouse, iDate) plus uC1..uC3 colours,
so a single-pass Shadertoy "Image" shader pasted by the user runs unchanged (no iChannel textures). The runtime marks the
canvases it adds with data-ld-ui, so the editor never saves them; it pauses off-screen and honours prefers-reduced-motion.
"""
from __future__ import annotations

import html as _html
import json
import re

COMMON = """float ld_hash(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
float ld_noise(vec2 p){vec2 i=floor(p),f=fract(p);vec2 u=f*f*(3.0-2.0*f);
 return mix(mix(ld_hash(i),ld_hash(i+vec2(1.0,0.0)),u.x),mix(ld_hash(i+vec2(0.0,1.0)),ld_hash(i+vec2(1.0,1.0)),u.x),u.y);}
float ld_fbm(vec2 p){float v=0.0,a=0.5;for(int i=0;i<5;i++){v+=a*ld_noise(p);p=p*2.03+vec2(1.7,9.2);a*=0.5;}return v;}
"""

SHADERS: dict[str, dict] = {
    "aurora": {"name": "Aurora", "colors": "#070b18,#22d3a6,#8b5cf6", "tags": "northern lights bands glow night", "glsl": """
void mainImage(out vec4 o, in vec2 fc){
  vec2 uv=fc/iResolution.xy; float t=iTime*0.15;
  vec3 col=uC1*(0.6+0.4*uv.y);
  for(int i=0;i<3;i++){ float fi=float(i);
    float y=0.55+0.12*fi+0.08*sin(uv.x*3.0+t*(1.0+fi)+fi)+0.1*(ld_fbm(vec2(uv.x*2.0+t,fi))-0.5);
    float band=exp(-pow((uv.y-y)*(9.0-fi*2.0),2.0));
    float flick=0.6+0.4*ld_noise(vec2(uv.x*12.0+fi*7.0,t*3.0));
    col+=mix(uC2,uC3,fi/2.0)*band*flick*0.75; }
  col+=0.03*(ld_hash(fc+iTime)-0.5);
  o=vec4(col,1.0);
}"""},
    "mesh": {"name": "Gradient mesh", "colors": "#ff7a59,#7c3aed,#06b6d4", "tags": "gradient blobs soft colorful grain", "glsl": """
void mainImage(out vec4 o, in vec2 fc){
  vec2 uv=fc/iResolution.xy; float t=iTime*0.2; vec2 asp=vec2(iResolution.x/iResolution.y,1.0);
  vec2 p1=vec2(0.3+0.2*sin(t*1.1),0.3+0.2*cos(t*0.9));
  vec2 p2=vec2(0.7+0.2*cos(t*0.7),0.4+0.25*sin(t*1.3));
  vec2 p3=vec2(0.5+0.25*sin(t*0.5+2.0),0.75+0.15*cos(t*1.7));
  float w1=1.0/(0.02+pow(length((uv-p1)*asp),2.0)), w2=1.0/(0.02+pow(length((uv-p2)*asp),2.0)), w3=1.0/(0.02+pow(length((uv-p3)*asp),2.0));
  vec3 col=(uC1*w1+uC2*w2+uC3*w3)/(w1+w2+w3);
  col+=0.04*(ld_hash(fc*0.5+floor(iTime*24.0))-0.5);
  o=vec4(col,1.0);
}"""},
    "plasma": {"name": "Plasma", "colors": "#1e1b4b,#db2777,#fbbf24", "tags": "psychedelic retro colorful waves", "glsl": """
void mainImage(out vec4 o, in vec2 fc){
  vec2 uv=(fc-0.5*iResolution.xy)/iResolution.y; float t=iTime*0.6;
  float v=sin(uv.x*6.0+t)+sin((uv.y*5.0-t)*1.1)+sin(length(uv*7.0)-t*1.3)+sin((uv.x+uv.y)*4.0+t*0.7);
  v=clamp(0.5+0.25*v,0.0,1.0);
  vec3 col=v<0.5?mix(uC1,uC2,v*2.0):mix(uC2,uC3,v*2.0-1.0);
  o=vec4(col,1.0);
}"""},
    "waves": {"name": "Line waves", "colors": "#0b0f19,#38bdf8,#f472b6", "tags": "lines flowing dark tech", "glsl": """
void mainImage(out vec4 o, in vec2 fc){
  vec2 uv=fc/iResolution.xy; float t=iTime*0.4; vec3 col=uC1;
  for(int i=0;i<14;i++){ float fi=float(i)/14.0;
    float y=fi+0.05*sin(uv.x*6.0+t+fi*10.0)+0.03*sin(uv.x*13.0-t*1.7+fi*4.0);
    float d=abs(uv.y-y)*iResolution.y;
    col+=mix(uC2,uC3,fi)*smoothstep(1.6,0.0,d)*0.8; }
  col+=0.05*(ld_hash(fc+fract(iTime)*100.0)-0.5);
  o=vec4(col,1.0);
}"""},
    "clouds": {"name": "Soft clouds", "colors": "#dbeafe,#ffffff,#93c5fd", "tags": "sky calm light airy noise", "glsl": """
void mainImage(out vec4 o, in vec2 fc){
  vec2 uv=fc/iResolution.y; float t=iTime*0.05;
  float n=ld_fbm(uv*3.0+vec2(t*2.0,t));
  n=ld_fbm(uv*3.0+n*1.5+vec2(-t,t*0.5));
  vec3 col=mix(uC1,uC2,smoothstep(0.25,0.75,n));
  col=mix(col,uC3,smoothstep(0.62,0.9,n)*0.6);
  o=vec4(col,1.0);
}"""},
    "stars": {"name": "Starfield", "colors": "#020617,#1e1b4b,#e0e7ff", "tags": "space night twinkle dark", "glsl": """
void mainImage(out vec4 o, in vec2 fc){
  vec3 col=mix(uC1,uC2,fc.y/iResolution.y*0.6);
  for(int l=0;l<3;l++){ float fl=float(l); float sc=40.0+fl*35.0;
    vec2 p=fc/iResolution.y*sc+vec2(iTime*(0.4+fl*0.5),0.0);
    vec2 id=floor(p), f=fract(p)-0.5; float h=ld_hash(id+fl*13.0);
    if(h>0.9){ vec2 off=vec2(ld_hash(id+1.3),ld_hash(id+7.1))-0.5; float d=length(f-off*0.6);
      float tw=0.6+0.4*sin(iTime*(2.0+h*5.0)+h*40.0);
      col+=uC3*smoothstep(0.08+0.04*(1.0-fl/3.0),0.0,d)*tw; } }
  o=vec4(col,1.0);
}"""},
    "halftone": {"name": "Halftone dots", "colors": "#fafaf9,#111827,#ef4444", "tags": "dots print pop editorial", "glsl": """
void mainImage(out vec4 o, in vec2 fc){
  float cell=14.0; vec2 g=floor(fc/cell), f=fract(fc/cell)-0.5;
  vec2 uv=g*cell/iResolution.xy; float t=iTime*0.5;
  float v=0.5+0.5*sin(length((uv-0.5)*vec2(iResolution.x/iResolution.y,1.0))*9.0-t*2.0);
  v*=0.55+0.45*ld_noise(uv*4.0+t*0.3);
  float r=0.08+0.38*v; float d1=smoothstep(r,r-0.08,length(f));
  o=vec4(mix(uC1,mix(uC2,uC3,uv.x),d1),1.0);
}"""},
    "ripple": {"name": "Ripple", "colors": "#0c4a6e,#38bdf8,#ffffff", "tags": "water rings interactive mouse", "glsl": """
void mainImage(out vec4 o, in vec2 fc){
  vec2 c=iMouse.z>0.0?iMouse.xy:0.5*iResolution.xy;
  float d=length(fc-c)/iResolution.y;
  float w=sin(d*40.0-iTime*3.0)*exp(-d*2.5);
  vec3 col=mix(uC1,uC2,0.5+0.5*w);
  col=mix(col,uC3,smoothstep(0.85,1.0,w)*0.6);
  o=vec4(col,1.0);
}"""},
    "sunset": {"name": "Retro sunset", "colors": "#1e1b4b,#f97316,#fde047", "tags": "retro 80s synthwave sun stripes", "glsl": """
void mainImage(out vec4 o, in vec2 fc){
  vec2 uv=fc/iResolution.xy; vec2 p=(fc-vec2(0.5*iResolution.x,0.42*iResolution.y))/iResolution.y;
  vec3 sky=mix(uC2,uC1,clamp(uv.y*1.3,0.0,1.0));
  float sun=smoothstep(0.262,0.25,length(p));
  float stripes=step(0.5,fract((p.y+iTime*0.03)*22.0));
  float cut=p.y<0.0?stripes*smoothstep(0.0,-0.2,p.y):0.0;
  o=vec4(mix(sky,uC3,sun*(1.0-cut)),1.0);
}"""},
    "liquid": {"name": "Liquid metal", "colors": "#0f172a,#94a3b8,#e2e8f0", "tags": "fluid chrome marble warp", "glsl": """
void mainImage(out vec4 o, in vec2 fc){
  vec2 uv=fc/iResolution.y*2.2; float t=iTime*0.08;
  vec2 q=vec2(ld_fbm(uv+t),ld_fbm(uv+vec2(5.2,1.3)-t));
  vec2 r=vec2(ld_fbm(uv+3.0*q+vec2(1.7,9.2)+t*1.5),ld_fbm(uv+3.0*q+vec2(8.3,2.8)-t));
  float f=ld_fbm(uv+3.0*r);
  vec3 col=mix(uC1,uC2,clamp(f*f*2.2,0.0,1.0));
  col=mix(col,uC3,clamp(length(q)*0.9-0.2,0.0,1.0)*0.7);
  o=vec4(col*(0.85+0.3*f),1.0);
}"""},
    "grid": {"name": "Horizon grid", "colors": "#0f0326,#ff2e88,#22d3ee", "tags": "synthwave retro perspective neon", "glsl": """
void mainImage(out vec4 o, in vec2 fc){
  vec2 uv=(fc-0.5*iResolution.xy)/iResolution.y; float hz=0.05;
  vec3 col=mix(uC1,uC2*0.7,smoothstep(0.45,-0.05,uv.y));
  if(uv.y<hz){ float z=0.35/(hz-uv.y+0.001); vec2 g=vec2(uv.x*z,z+iTime*1.2);
    vec2 d=0.5-abs(fract(g)-0.5); vec2 w=fwidth(g);
    float line=max(1.0-smoothstep(0.0,w.x*1.5,d.x),1.0-smoothstep(0.0,w.y*1.5,d.y));
    col=mix(uC1*0.5,uC3,line*smoothstep(30.0,2.0,z)); }
  o=vec4(col,1.0);
}"""},
    "topo": {"name": "Topography", "colors": "#f5f0e6,#3f3a33,#c2410c", "tags": "contour map lines editorial calm", "glsl": """
void mainImage(out vec4 o, in vec2 fc){
  vec2 uv=fc/iResolution.y*3.0;
  float n=ld_fbm(uv+vec2(iTime*0.03,-iTime*0.02));
  float k=n*18.0; float f=abs(fract(k)-0.5); float w=fwidth(k);
  float line=1.0-smoothstep(0.0,w*1.2,0.5-f);
  vec3 col=mix(uC1,uC2,line*0.8);
  col=mix(col,uC3,smoothstep(0.7,0.8,n)*line);
  o=vec4(col,1.0);
}"""},
}

ASCII: dict[str, dict] = {
    "field": {"name": "ASCII field", "tags": "flowing characters terminal texture"},
    "wave": {"name": "ASCII wave", "tags": "interference ripple terminal"},
    "orb": {"name": "ASCII orb", "tags": "rotating sphere 3d terminal"},
    "rain": {"name": "ASCII rain", "tags": "falling characters code matrix"},
}

_RUNTIME = r"""(()=>{if(window.__ldfx)return;window.__ldfx=1;
const S=window.__ldShaders=Object.assign(window.__ldShaders||{},__SHADERS__);const COMMON=__COMMON__;
const HEAD="#version 300 es\nprecision highp float;precision highp int;\nuniform vec3 iResolution;uniform float iTime;uniform float iTimeDelta;uniform int iFrame;uniform vec4 iMouse;uniform vec4 iDate;uniform vec3 uC1;uniform vec3 uC2;uniform vec3 uC3;\nout vec4 ld_out;\n";
const TAIL="\nvoid main(){vec4 c=vec4(0.0);mainImage(c,gl_FragCoord.xy);ld_out=vec4(c.rgb,1.0);}";
const VS="#version 300 es\nin vec2 p;void main(){gl_Position=vec4(p,0.0,1.0);}";
const RM=matchMedia("(prefers-reduced-motion: reduce)").matches;
const css=document.createElement("style");css.setAttribute("data-ld-ui","1");
css.textContent=":where([data-ld-shader],[data-ld-ascii]){position:relative;isolation:isolate}:where([data-ld-shader],[data-ld-ascii])>:not([data-ld-ui]){position:relative;z-index:1}";
(document.head||document.documentElement).appendChild(css);
const hex=h=>{h=String(h||"").trim().replace("#","");if(h.length===3)h=h.split("").map(c=>c+c).join("");const n=parseInt(h,16);return isNaN(n)?null:[(n>>16&255)/255,(n>>8&255)/255,(n&255)/255]};
const watch=(el,cb)=>{const io=new IntersectionObserver(es=>cb(es[es.length-1].isIntersecting));io.observe(el);};
function mountShader(el){if(el.__ld)return;el.__ld=1;
 const id=el.getAttribute("data-ld-shader"),own=el.querySelector('script[type="x-shader/x-fragment"]'),def=S[id]||{},src=own?own.textContent:def.glsl;if(!src)return;
 const cols=(el.getAttribute("data-ld-colors")||def.colors||"#111827,#6366f1,#22d3ee").split(",").map(hex);while(cols.length<3)cols.push(cols[cols.length-1]||[0,0,0]);
 const cv=document.createElement("canvas");cv.setAttribute("data-ld-ui","1");cv.setAttribute("aria-hidden","true");
 cv.style.cssText="position:absolute;inset:0;width:100%;height:100%;z-index:0;pointer-events:none;display:block;border-radius:inherit";el.prepend(cv);
 const fail=msg=>{cv.style.background="linear-gradient(135deg,rgb("+cols.map(c=>c.map(v=>Math.round(v*255)).join(",")).join("),rgb(")+"))";if(msg&&el.hasAttribute("data-ld-debug")){const d=document.createElement("pre");d.setAttribute("data-ld-ui","1");d.style.cssText="position:absolute;left:6px;bottom:6px;right:6px;margin:0;font:10px/1.3 monospace;color:#f87171;white-space:pre-wrap;z-index:2;max-height:60%;overflow:auto";d.textContent=msg;el.appendChild(d);}};
 const gl=cv.getContext("webgl2",{antialias:false,premultipliedAlpha:false,preserveDrawingBuffer:true});if(!gl){fail("WebGL2 not available");return;}
 const sh=(type,s)=>{const x=gl.createShader(type);gl.shaderSource(x,s);gl.compileShader(x);if(!gl.getShaderParameter(x,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(x));return x;};
 let pr;try{pr=gl.createProgram();gl.attachShader(pr,sh(gl.VERTEX_SHADER,VS));gl.attachShader(pr,sh(gl.FRAGMENT_SHADER,HEAD+COMMON+src+TAIL));gl.linkProgram(pr);if(!gl.getProgramParameter(pr,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(pr));}catch(e){fail("shader error: "+e.message);return;}
 gl.useProgram(pr);const b=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),gl.STATIC_DRAW);
 const loc=gl.getAttribLocation(pr,"p");gl.enableVertexAttribArray(loc);gl.vertexAttribPointer(loc,2,gl.FLOAT,false,0,0);
 const U={};["iResolution","iTime","iTimeDelta","iFrame","iMouse","iDate","uC1","uC2","uC3"].forEach(n=>U[n]=gl.getUniformLocation(pr,n));
 gl.uniform3fv(U.uC1,cols[0]);gl.uniform3fv(U.uC2,cols[1]);gl.uniform3fv(U.uC3,cols[2]);
 const speed=parseFloat(el.getAttribute("data-ld-speed")||"1")||1,dpr=Math.min(1.5,devicePixelRatio||1);
 let t0=performance.now(),last=t0,frame=0,mouse=[0,0,0,0],vis=true,run=true;
 el.addEventListener("pointermove",e=>{const r=cv.getBoundingClientRect();mouse=[(e.clientX-r.left)*dpr,(r.bottom-e.clientY)*dpr,1,0]});
 el.addEventListener("pointerleave",()=>{mouse[2]=0});watch(el,v=>{vis=v;if(v&&run&&!RM)requestAnimationFrame(loop)});
 function draw(now){const w=Math.max(1,Math.round(cv.clientWidth*dpr)),h=Math.max(1,Math.round(cv.clientHeight*dpr));if(cv.width!==w||cv.height!==h){cv.width=w;cv.height=h;}
  gl.viewport(0,0,w,h);const t=(now-t0)/1000*speed,d=new Date();gl.uniform3f(U.iResolution,w,h,1);gl.uniform1f(U.iTime,RM?2.5:t);gl.uniform1f(U.iTimeDelta,(now-last)/1000);
  gl.uniform1i(U.iFrame,frame++);gl.uniform4fv(U.iMouse,mouse);gl.uniform4f(U.iDate,d.getFullYear(),d.getMonth(),d.getDate(),d.getHours()*3600+d.getMinutes()*60+d.getSeconds());gl.drawArrays(gl.TRIANGLES,0,3);last=now;}
 function loop(now){if(!el.isConnected){run=false;return;}if(!vis)return;draw(now);if(!RM)requestAnimationFrame(loop);}
 requestAnimationFrame(loop);}
const RAMP=" .:-=+*#%@";
const A={field:(x,y,t)=>0.5+0.5*Math.sin(x*0.16+t)*Math.cos(y*0.3-t*0.7)*Math.sin((x+y)*0.06+t*0.4),
 wave:(x,y,t,w,h)=>{const cx=x/w-0.5,cy=(y/h-0.5)*0.5*h/w*2;const d1=Math.hypot(cx-0.2*Math.sin(t*0.3),cy),d2=Math.hypot(cx+0.25,cy+0.1*Math.cos(t*0.4));return 0.5+0.25*(Math.sin(d1*40-t*3)+Math.sin(d2*34-t*2.4));},
 orb:(x,y,t,w,h)=>{const s=Math.min(w*0.5,h)*0.42,nx=(x-w/2)/(s*2),ny=(y-h/2)/s,r=nx*nx+ny*ny;if(r>1)return 0;const nz=Math.sqrt(1-r),L=[Math.cos(t*0.7),-0.5,Math.sin(t*0.7)],ll=Math.hypot(...L);
  let b=Math.max(0,(nx*L[0]+ny*L[1]+nz*L[2])/ll);const lon=Math.atan2(nx,nz)+t*0.8,lat=Math.asin(Math.max(-1,Math.min(1,ny)));if(Math.sin(lon*8)*Math.sin(lat*8)>0)b*=0.62;return 0.08+0.92*b;},
 rain:(x,y,t,w,h)=>{const hs=Math.sin(x*12.9898+1.7)*43758.5453,r=hs-Math.floor(hs);if(r<0.45)return 0;const sp=3+r*8,len=3+r*Math.max(3,h*0.35),head=(t*sp+r*h*5)%(h+len*2);const d=head-y;return d<0||d>len?0:1-d/len;}};
function mountAscii(el){if(el.__ld)return;el.__ld=1;const fn=A[el.getAttribute("data-ld-ascii")]||A.field,rain=fn===A.rain;
 const pre=document.createElement("pre");pre.setAttribute("data-ld-ui","1");pre.setAttribute("aria-hidden","true");
 pre.style.cssText="position:absolute;inset:0;margin:0;overflow:hidden;font:"+(el.getAttribute("data-ld-size")||"12")+"px/1 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:0;white-space:pre;pointer-events:none;user-select:none;z-index:0;color:inherit;opacity:"+(el.getAttribute("data-ld-opacity")||"0.9");
 el.prepend(pre);const m=document.createElement("span");m.textContent="MMMMMMMMMM";pre.appendChild(m);const cw=m.getBoundingClientRect().width/10||7,ch=m.getBoundingClientRect().height||12;pre.textContent="";
 let vis=true,lastF=0;const t0=performance.now(),speed=parseFloat(el.getAttribute("data-ld-speed")||"1")||1;watch(el,v=>{vis=v;if(v&&!RM)requestAnimationFrame(loop)});
 function draw(now){const cols=Math.max(1,Math.floor(el.clientWidth/cw)),rows=Math.max(1,Math.floor(el.clientHeight/ch)),t=RM?3:(now-t0)/1000*speed;let out="";
  for(let y=0;y<rows;y++){for(let x=0;x<cols;x++){const v=fn(x,y,t,cols,rows);if(rain){const k=Math.sin((x*7.13+y*3.7+Math.floor(t*3+x))*12.9898)*43758.5453;out+=v>0.05?String.fromCharCode(33+Math.floor((k-Math.floor(k))*90)):" ";}else out+=RAMP[Math.max(0,Math.min(9,Math.floor(v*9.99)))];}out+="\n";}
  pre.textContent=out;}
 function loop(now){if(!el.isConnected||!vis)return;if(now-lastF>45){draw(now);lastF=now;}if(!RM)requestAnimationFrame(loop);}
 requestAnimationFrame(now=>{draw(now);if(!RM)requestAnimationFrame(loop);});}
function scan(r){if(!r.querySelectorAll)return;if(r.matches&&r.matches("[data-ld-shader]"))mountShader(r);if(r.matches&&r.matches("[data-ld-ascii]"))mountAscii(r);
 r.querySelectorAll("[data-ld-shader]").forEach(mountShader);r.querySelectorAll("[data-ld-ascii]").forEach(mountAscii);}
const go=()=>{scan(document);new MutationObserver(ms=>ms.forEach(m=>m.addedNodes.forEach(n=>{if(n.nodeType===1&&!n.hasAttribute("data-ld-ui"))scan(n)}))).observe(document.documentElement,{childList:true,subtree:true});};
document.readyState==="loading"?addEventListener("DOMContentLoaded",go):go();})();"""

RUNTIME_JS = _RUNTIME.replace("__SHADERS__", json.dumps({k: {"glsl": v["glsl"].strip(), "colors": v["colors"]} for k, v in SHADERS.items()}, separators=(",", ":"))).replace("__COMMON__", json.dumps(COMMON))
RUNTIME_TAG = f'<script data-ld-lib="fx-runtime">{RUNTIME_JS}</script>'
_USES = re.compile(r"\sdata-ld-(?:shader|ascii)\s*=")


def inject(html: str) -> str:
    """Add the effects runtime to a page that uses data-ld-shader / data-ld-ascii (once)."""
    if not html or not _USES.search(html) or 'data-ld-lib="fx-runtime"' in html:
        return html
    i = html.lower().rfind("</body>")
    return html[:i] + RUNTIME_TAG + html[i:] if i >= 0 else html + RUNTIME_TAG


def prompt_block() -> str:
    """Told to the HTML engine when the style calls for effects (or the brief asks for them)."""
    return ("Visual effects available — no code needed, localdesign adds the runtime:\n"
            "- Animated GPU background: put data-ld-shader=\"<name>\" on a hero/section/card container (give it a min-height; its content stays on top). "
            "Optional data-ld-colors=\"#bg,#accent1,#accent2\" to match the palette, data-ld-speed=\"0.5\". Names: "
            + ", ".join(f"{k} ({v['name'].lower()})" for k, v in SHADERS.items()) + ".\n"
            "- Animated ASCII art: an empty element with data-ld-ascii=\"<name>\" and a min-height (characters use the text colour; data-ld-size=\"10\" for smaller). Names: "
            + ", ".join(ASCII) + ".\n"
            "Use at most one or two effects per screen, keep text readable on top (a translucent panel helps), and never write your own canvas/WebGL code for these.")


def demo(kind: str, key: str) -> str:
    """Markup for a kit item / preview: an effect block with editable placeholder content."""
    if kind == "shader":
        s = SHADERS[key]
        dark = key not in ("clouds", "halftone", "topo")
        return (f'<section data-ld-shader="{key}" data-ld-colors="{s["colors"]}" style="min-height:320px;display:grid;place-items:center;padding:56px 24px;'
                f'color:{"#fff" if dark else "#111"};text-align:center;font-family:system-ui,sans-serif">'
                f'<div><h2 style="margin:0 0 8px;font-size:34px;letter-spacing:-.02em">{s["name"]}</h2><p style="margin:0;opacity:.8">Headline and copy sit on top of the effect.</p></div></section>')
    a = ASCII[key]
    return (f'<div data-ld-ascii="{key}" style="min-height:260px;background:#0a0a0a;color:#4ade80;border-radius:12px;overflow:hidden" '
            f'aria-label="{a["name"]}"></div>')


def kit_items() -> dict[str, list[dict]]:
    """Built-in, always-available kits for the UI kits browser."""
    sh = [{"id": f"shader-{k}", "name": v["name"], "category": "Shaders", "author": "localdesign", "tags": v["tags"].split(),
           "html": demo("shader", k) + RUNTIME_TAG, "css": "", "scope": "", "fx": True} for k, v in SHADERS.items()]
    asc = [{"id": f"ascii-{k}", "name": v["name"], "category": "ASCII", "author": "localdesign", "tags": v["tags"].split(),
            "html": demo("ascii", k) + RUNTIME_TAG, "css": "", "scope": "", "fx": True} for k, v in ASCII.items()]
    return {"fx-shaders": sh, "fx-ascii": asc}


SHADERTOY_LICENSE = "CC BY-NC-SA 3.0 (Shadertoy default: non-commercial, attribution, share-alike) unless the author states otherwise"


def detect_license(glsl: str) -> str:
    low = (glsl or "").lower()
    for pat, name in [(r"\bmit\b", "MIT"), (r"cc0|public domain|unlicense", "Public domain / CC0"), (r"cc[- ]by[- ]nc[- ]sa|attribution-noncommercial-sharealike", "CC BY-NC-SA"),
                      (r"cc[- ]by[- ]sa|attribution-sharealike", "CC BY-SA"), (r"cc[- ]by\b|creative commons attribution", "CC BY"), (r"apache", "Apache-2.0"), (r"\bbsd\b", "BSD")]:
        if re.search(pat, low):
            return name
    return SHADERTOY_LICENSE


def custom_shader_html(glsl: str, name: str, credit: str) -> str:
    safe = (glsl or "").replace("</script", "<\\/script")
    return (f'<section data-ld-shader="custom" style="min-height:320px;display:grid;place-items:center;padding:56px 24px;color:#fff;text-align:center;font-family:system-ui,sans-serif">'
            f'<script type="x-shader/x-fragment">// {credit.replace(chr(10), " ")}\n{safe}</script><div><h2 style="margin:0 0 8px;font-size:34px">{_html.escape(name)}</h2></div></section>')

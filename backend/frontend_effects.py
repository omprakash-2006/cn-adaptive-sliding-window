"""Presentation-only effects. No database, admission or protocol dependencies."""

FRONT_STYLE = r'''
html{background:#103051}body{overflow-x:hidden;background-color:#103051}
body:before{content:"";position:fixed;inset:0;background:linear-gradient(110deg,#05234c99,#0722473d 55%,#081b4190);pointer-events:none;z-index:0}
.login-area{max-width:800px;width:calc(100% - 64px);z-index:2}.portal-card{border-radius:18px;margin:0 -15px;position:relative;transform:perspective(1400px) rotateX(var(--card-x,0deg)) rotateY(var(--card-y,0deg));transform-style:preserve-3d;box-shadow:0 38px 90px #04153180,0 3px 0 #ffffff22,0 0 0 1px #ffffff60;transition:transform .22s ease-out;isolation:isolate}
.portal-card:before{content:"";position:absolute;inset:-7px;border:1px solid #ffffff2b;border-radius:24px;pointer-events:none;transform:translateZ(-14px)}
.left-panel{border-radius:18px 0 0 18px;position:relative;background:#007bff;box-shadow:inset 0 1px 0 #ffffff60;overflow:hidden}
.left-panel:before{content:"";position:absolute;width:350px;height:350px;border-radius:50%;border:1px solid #ffffff20;left:-220px;bottom:-160px;box-shadow:0 0 0 35px #ffffff06,0 0 0 70px #ffffff05;pointer-events:none}
.left-panel:after{content:"";position:absolute;inset:0;background:linear-gradient(135deg,#ffffff10,transparent 45%,#00285d15);pointer-events:none}
.left-pannel{position:relative;z-index:1;margin:58px 0}.crest-wrap{position:relative;transform:translateZ(30px)}
.crest-wrap:before{content:"";position:absolute;width:176px;height:176px;border:1px solid #ffffff55;box-shadow:0 0 0 9px #ffffff08,0 10px 32px #004e9c2b;border-radius:50%;left:50%;top:50%;transform:translate(-50%,-50%);pointer-events:none}
.crest-img{filter:drop-shadow(0 9px 5px #00377340)}.college-name-left{position:relative;text-shadow:0 2px 7px #0052ac40}.btn-circular{box-shadow:0 4px 0 #9b402c,0 12px 20px #00489c35;transition:transform .15s,box-shadow .15s}.btn-circular:hover{transform:translateY(-2px);box-shadow:0 6px 0 #9b402c,0 16px 22px #00489c35}
.right-panel{border-radius:0 18px 18px 0;background:linear-gradient(145deg,#fff,#f9fcff);box-shadow:inset 0 1px 0 #fff}.right-side{margin:30px 0}.main-heading{font-size:27px}.main-heading hr{border-color:#dbe8f7}.sub-heading{font-size:23px}.course-links{font-size:14px;line-height:22px}.dotted-line{color:#8769c2;font-size:15px}.login-box{padding-top:18px;margin-top:18px}.mepco-input{border-color:#d0deed;background:#fff;border-radius:7px;box-shadow:0 2px 4px #15477404;font-size:15px}.mepco-input:focus{box-shadow:0 0 0 4px #007bff12}.input-range{margin-top:6px;color:#697d94;font-size:10px;font-weight:400}.btn-results{margin-top:30px;border-radius:7px;box-shadow:0 5px 0 #005ed0,0 13px 24px #006cff24;transition:transform .15s,box-shadow .15s}.btn-results:hover{transform:translateY(-2px);box-shadow:0 7px 0 #005ed0,0 17px 28px #006cff30}.btn-results:active{transform:translateY(2px);box-shadow:0 2px 0 #005ed0}.scene-light{position:fixed;width:350px;height:350px;border-radius:50%;filter:blur(70px);pointer-events:none;z-index:0;opacity:.25}.scene-light.one{background:#1597ff;top:-170px;left:-100px}.scene-light.two{background:#ffd28b;bottom:-200px;right:-130px;opacity:.14}.scene-line{position:fixed;width:160px;height:160px;border:1px solid #ffffff1c;border-radius:28px;pointer-events:none;z-index:0;transform:rotate(-22deg)}.scene-line.one{left:7%;top:15%}.scene-line.two{right:7%;bottom:12%;transform:rotate(22deg);width:120px;height:120px}
@media(max-width:767px){.login-area{max-width:450px;width:calc(100% - 36px);margin:28px auto}.portal-card{margin:0;transform:none!important}.left-panel{border-radius:18px 18px 0 0}.right-panel{border-radius:0 0 18px 18px}.left-pannel{margin:25px 0}.crest-wrap:before{width:120px;height:120px}.right-side{margin:28px 0}.main-heading{font-size:24px}.sub-heading{font-size:21px}.scene-line{display:none}.course-links{font-size:12px;line-height:21px}.college-name-left{font-size:12px}.btn-circular{box-shadow:0 3px 0 #9b402c;transform:none}.btn-results{font-size:18px}.scene-light{opacity:.1}}
@media(max-width:360px){.main-heading{font-size:20px}.sub-heading{font-size:19px}.college-name-left{font-size:10px}.right-panel{padding:0 17px}.course-links{font-size:11px}}
@media(prefers-reduced-motion:reduce){.portal-card{transform:none!important;transition:none}.crest-wrap{transform:none}.btn-results,.btn-circular{transition:none}.btn-results:hover,.btn-circular:hover{transform:none}}
'''

FRONT_SCRIPT = r'''
<script>
(() => {
  const card=document.querySelector('.portal-card');
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  const canTilt=matchMedia('(pointer: fine) and (min-width: 768px)');
  let scheduled=0,lastEvent=null;
  const reset=()=>{card.style.setProperty('--card-x','0deg');card.style.setProperty('--card-y','0deg');};
  card.addEventListener('pointermove',e=>{
    if(reduced.matches||!canTilt.matches||card.contains(document.activeElement))return;
    lastEvent=e;
    if(scheduled)return;
    scheduled=requestAnimationFrame(()=>{scheduled=0;const r=card.getBoundingClientRect();
      const x=Math.max(-1,Math.min(1,(lastEvent.clientX-r.left)/r.width*2-1));
      const y=Math.max(-1,Math.min(1,(lastEvent.clientY-r.top)/r.height*2-1));
      card.style.setProperty('--card-x',(-y*1.8)+'deg');card.style.setProperty('--card-y',(x*2.4)+'deg');
    });
  });
  card.addEventListener('pointerleave',reset);card.addEventListener('focusin',reset);
  reduced.addEventListener('change',reset);
  const dob=document.getElementById('dobInput');
  dob.addEventListener('input',()=>dob.setCustomValidity(''));
  document.querySelector('form').addEventListener('submit',e=>{
    const m=dob.value.match(/^(\d{2})-(\d{2})-(\d{4})$/);
    const d=m?new Date(Number(m[3]),Number(m[2])-1,Number(m[1])):null;
    const valid=m&&Number(m[3])>=1900&&d.getFullYear()===Number(m[3])&&d.getMonth()+1===Number(m[2])&&d.getDate()===Number(m[1])&&d<=new Date();
    if(!valid){dob.setCustomValidity('Enter a real date of birth in dd-mm-yyyy format.');e.preventDefault();e.stopImmediatePropagation();dob.reportValidity();}
  },true);
})();
</script>
'''


def enhance_portal(html):
    html = html.replace("</style>", FRONT_STYLE + "</style>", 1)
    html = html.replace("<body>", '<body><div class="scene-light one" aria-hidden="true"></div>'
                        '<div class="scene-light two" aria-hidden="true"></div>'
                        '<div class="scene-line one" aria-hidden="true"></div>'
                        '<div class="scene-line two" aria-hidden="true"></div>', 1)
    html = html.replace('autocomplete="off"', 'autocomplete="off" autocapitalize="characters"', 1)
    html = html.replace('spellcheck="false" required></div>',
                        'spellcheck="false" required><div class="input-range">24BAD001 – 24BAD130</div></div>', 1)
    return html.replace("</body>", FRONT_SCRIPT + "</body>", 1)


CONFETTI = r'''
<style>.result-celebration{position:fixed;inset:0;pointer-events:none;overflow:hidden;z-index:9999}.result-ribbon{position:absolute;left:0;top:0;display:block;border-radius:1px;box-shadow:0 1px 2px #0001;will-change:transform,opacity}@media print{.result-celebration{display:none!important}}@media(prefers-reduced-motion:reduce){.result-celebration{display:none!important}}</style>
<script>
(() => {
  if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  let started=false;
  function burst(){
    if(started||document.visibilityState!=='visible')return;
    started=true;document.removeEventListener('visibilitychange',burst);
    const layer=document.createElement('div');layer.className='result-celebration';layer.setAttribute('aria-hidden','true');document.body.append(layer);
    const colors=['#007bff','#ffb23e','#ff6600','#65b8ff','#dbeeff','#b899ec'];
    for(let i=0;i<72;i++){
      const piece=document.createElement('span');piece.className='result-ribbon';
      const side=i%2,x=side?innerWidth-8:8,startY=innerHeight*.3;
      const targetX=innerWidth*(.15+Math.random()*.7),peakY=-80-Math.random()*160;
      const rotation=(Math.random()-.5)*1100;
      piece.style.width=(4+Math.random()*5)+'px';piece.style.height=(10+Math.random()*15)+'px';piece.style.background=colors[i%colors.length];layer.append(piece);
      piece.animate([
        {transform:`translate3d(${x}px,${startY}px,0) rotate(0deg)`,opacity:0},
        {transform:`translate3d(${targetX}px,${peakY}px,0) rotate(${rotation*.4}deg)`,opacity:1,offset:.27},
        {transform:`translate3d(${targetX+(Math.random()-.5)*180}px,${innerHeight+100}px,0) rotate(${rotation}deg)`,opacity:0}
      ],{duration:1900+Math.random()*1000,delay:Math.random()*170,easing:'cubic-bezier(.14,.52,.65,1)',fill:'forwards'});
    }
    setTimeout(()=>layer.remove(),3300);
  }
  addEventListener('beforeprint',()=>document.querySelector('.result-celebration')?.remove(),{once:true});
  document.addEventListener('visibilitychange',burst);burst();
})();
</script>
'''

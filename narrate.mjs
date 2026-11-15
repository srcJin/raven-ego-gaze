// Generate Cartesia narration in aligned chapters. Requires Node 20+ and FFmpeg.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
const root=path.dirname(fileURLToPath(import.meta.url));
const flag=process.argv.indexOf('--env-file');
const envFile=flag>=0 ? process.argv[flag+1] : process.env.CARTESIA_ENV_FILE || path.join(root,'.env');
if (envFile && fs.existsSync(envFile)) {
  for (const line of fs.readFileSync(envFile,'utf8').split(/\r?\n/)) {
    const match=line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (match && !process.env[match[1]]) process.env[match[1]]=match[2].replace(/^(['"])(.*)\1$/,'$2');
  }
}
if (!process.env.CARTESIA_API_KEY) throw new Error('Set CARTESIA_API_KEY in a private env file.');
const segments=JSON.parse(fs.readFileSync(path.join(root,'media/narration-segments.json'),'utf8'));
const timeline=[];
let start=0;
for (let index=0; index<segments.length; index++) {
  const response=await fetch('https://api.cartesia.ai/tts/bytes',{
    method:'POST',
    headers:{Authorization:`Bearer ${process.env.CARTESIA_API_KEY}`,'Cartesia-Version':process.env.CARTESIA_API_VERSION || '2026-08-14','Content-Type':'application/json'},
    body:JSON.stringify({model_id:process.env.CARTESIA_MODEL || 'sonic-3.6',transcript:segments[index],voice:process.env.CARTESIA_VOICE_ID || 'db6b0ed5-d5d3-463d-ae85-518a07d3c2b4',language:'en',output_format:{container:'wav',encoding:'pcm_s16le',sample_rate:44100},generation_config:{speed:1.05}}),
    signal:AbortSignal.timeout(120000),
  });
  if (!response.ok) throw new Error(`Cartesia HTTP ${response.status}; check credentials and model access.`);
  const file=path.join(root,`media/voice-${index}.wav`);
  fs.writeFileSync(file,Buffer.from(await response.arrayBuffer()));
  const duration=Number(execFileSync('ffprobe',['-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',file],{encoding:'utf8'}).trim());
  if (!Number.isFinite(duration) || duration<1) throw new Error('Invalid narration output.');
  const padded=Math.ceil((Math.max(duration+0.8,8))*25)/25;
  timeline.push({index,start,duration:padded,transcript:segments[index]});
  execFileSync('ffmpeg',['-y','-i',file,'-af','apad','-t',String(padded),path.join(root,`media/chapter-${index}.wav`)],{stdio:['ignore','ignore','pipe']});
  start+=padded;
}
fs.writeFileSync(path.join(root,'media/timeline.json'),JSON.stringify({duration:start,chapters:timeline},null,2)+'\n');
const inputs=timeline.flatMap(({index})=>['-i',path.join(root,`media/chapter-${index}.wav`)]);
execFileSync('ffmpeg',['-y',...inputs,'-filter_complex',`${timeline.map(({index})=>`[${index}:a]`).join('')}concat=n=${timeline.length}:v=0:a=1[out]`,'-map','[out]',path.join(root,'media/narration.wav')],{stdio:['ignore','ignore','pipe']});
console.log(`Created ${timeline.length} aligned narration chapters, ${start.toFixed(2)} seconds.`);

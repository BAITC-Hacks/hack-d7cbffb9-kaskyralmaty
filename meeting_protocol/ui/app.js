// Upload form, browser recording (mic + tab/system audio mixed via Web Audio) and async submit.
const $ = (id) => document.getElementById(id);
const form = $('form'), audioInput = $('audio'), submit = $('submit');
let recorded = null;          // File produced by the recorder
let selection = 0;

function setFile(file, label) {
  $('drop-title').textContent = file ? file.name : 'Перетащите запись или выберите файл';
  $('drop-sub').textContent = file ? label || `${(file.size / 1048576).toFixed(1)} МБ` : 'MP3, M4A, WAV, WEBM · до 100 МБ';
  submit.disabled = !file;
}

// Tabs
document.querySelectorAll('.tab').forEach((tab) => tab.addEventListener('click', () => {
  document.querySelectorAll('.tab').forEach((t) => t.setAttribute('aria-selected', String(t === tab)));
  document.querySelectorAll('[data-panel]').forEach((p) => { p.hidden = p.dataset.panel !== tab.dataset.tab; });
  submit.disabled = tab.dataset.tab === 'record' ? !recorded : !audioInput.files[0];
}));

// Upload: known case MP3s fill topic and participants by content hash
async function onFile(file) {
  const current = ++selection;
  recorded = null;
  setFile(file);
  if (!file) return;
  submit.disabled = true;
  try {
    let preset;
    if (file.size <= 100 * 1024 * 1024 && crypto.subtle) {
      const hash = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
      const digest = Array.from(new Uint8Array(hash), (b) => b.toString(16).padStart(2, '0')).join('');
      preset = PRESETS[digest];
    }
    if (current !== selection) return;
    if (preset) {
      $('topic').value = preset.topic || '';
      $('participants').value = (preset.participants || []).join('\n');
    }
    $('context-note').textContent = preset ? `Тема и участники заполнены: ${preset.label}. Проверьте перед отправкой.` : 'Укажите тему и участников — так имена в протоколе будут точнее.';
  } catch {
    $('context-note').textContent = 'Не удалось заполнить поля автоматически — введите тему и участников вручную.';
  } finally {
    if (current === selection) submit.disabled = false;
  }
}
audioInput.addEventListener('change', (e) => onFile(e.target.files[0]));
const drop = $('drop');
['dragover', 'dragenter'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove('over')));
drop.addEventListener('drop', (e) => {
  e.preventDefault();
  const file = e.dataTransfer.files[0];
  if (!file) return;
  const dt = new DataTransfer(); dt.items.add(file); audioInput.files = dt.files;
  onFile(file);
});

// Recording
const consent = $('consent'), startBtn = $('rec-start'), stopBtn = $('rec-stop'), note = $('rec-note');
if (REPLAY) { consent.disabled = true; } else { note.textContent = 'Отметьте согласие, затем начните запись.'; }
consent.addEventListener('change', () => { startBtn.disabled = !consent.checked; });
let recorder, streams = [], context, timer, started;

function stopStreams() {
  streams.forEach((s) => s.getTracks().forEach((t) => t.stop()));
  streams = [];
  if (context) context.close();
  context = null;
  clearInterval(timer);
}

startBtn.addEventListener('click', async () => {
  $('error').hidden = true;
  try {
    const mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    streams.push(mic);
    context = new AudioContext();
    const mix = context.createMediaStreamDestination();
    const analyser = context.createAnalyser();
    context.createMediaStreamSource(mic).connect(mix);
    context.createMediaStreamSource(mic).connect(analyser);
    let tabNote = 'Записывается только микрофон.';
    if ($('with-tab').checked) {
      try {
        const display = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
        streams.push(display);
        if (display.getAudioTracks().length) {
          const tab = context.createMediaStreamSource(new MediaStream(display.getAudioTracks()));
          tab.connect(mix); tab.connect(analyser);
          tabNote = 'Записываются микрофон и звук выбранной вкладки/экрана.';
        } else {
          tabNote = '⚠️ Звук собеседников НЕ записывается: при выборе вкладки не отмечено «Поделиться звуком». Остановите и начните заново, если нужны все участники.';
        }
      } catch {
        tabNote = '⚠️ Доступ к вкладке/экрану не дан — записывается только микрофон, голоса собеседников не попадут в протокол.';
      }
    }
    note.textContent = tabNote;
    const type = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : '';
    recorder = new MediaRecorder(mix.stream, type ? { mimeType: type } : {});
    const chunks = [];
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.onstop = () => {
      const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
      recorded = new File([blob], `meeting-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-')}.webm`, { type: blob.type });
      stopStreams();
      $('rec').classList.remove('recording');
      startBtn.hidden = false; stopBtn.hidden = true;
      note.textContent = `Запись готова: ${$('timer').textContent}, ${(blob.size / 1048576).toFixed(1)} МБ. Заполните участников и нажмите «Получить протокол».`;
      submit.disabled = false;
    };
    recorder.start(1000);
    started = Date.now();
    const level = new Uint8Array(analyser.fftSize);
    timer = setInterval(() => {
      const s = Math.floor((Date.now() - started) / 1000);
      $('timer').textContent = `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
      analyser.getByteTimeDomainData(level);
      const peak = Math.max(...level.map((v) => Math.abs(v - 128))) / 128;
      $('level').style.width = `${Math.min(100, peak * 140)}%`;
    }, 100);
    $('rec').classList.add('recording');
    startBtn.hidden = true; stopBtn.hidden = false; submit.disabled = true;
  } catch (error) {
    stopStreams();
    note.textContent = `Не удалось начать запись: ${error.message}. Разрешите доступ к микрофону.`;
  }
});
stopBtn.addEventListener('click', () => recorder && recorder.state !== 'inactive' && recorder.stop());

// Async submit: stay on the page and show readable errors instead of raw JSON
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const recordMode = document.querySelector('.tab[aria-selected="true"]').dataset.tab === 'record';
  const data = new FormData(form);
  if (recordMode) data.set('audio', recorded);
  if (!data.get('audio') || !data.get('audio').size) return;
  $('error').hidden = true;
  submit.disabled = true;
  form.classList.add('busy');
  const steps = [...document.querySelectorAll('.step')];
  let i = 0;
  steps[0].classList.add('on');
  const ticker = setInterval(() => { if (i < steps.length - 1) steps[++i].classList.add('on'); }, 12000);
  try {
    const response = await fetch(form.action, { method: 'POST', body: data });
    if (response.ok && response.redirected) { location.href = response.url; return; }
    let detail = `Ошибка ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch {}
    throw new Error(detail);
  } catch (error) {
    $('error').textContent = error.message;
    $('error').hidden = false;
    form.classList.remove('busy');
    steps.forEach((s) => s.classList.remove('on'));
    submit.disabled = false;
  } finally {
    clearInterval(ticker);
  }
});

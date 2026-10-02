// WebAudio recorder helper for editor interface
// Usage: include and call startRecording()/stopRecording() to obtain a Blob
let mediaRecorder = null;
let audioChunks = [];

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  mediaRecorder = new MediaRecorder(stream);
  audioChunks = [];
  mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
  mediaRecorder.start();
}

async function stopRecording() {
  return new Promise((resolve, reject) => {
	if (!mediaRecorder) return resolve(null);
	mediaRecorder.onstop = () => {
	  const blob = new Blob(audioChunks, { type: 'audio/wav' });
	  resolve(blob);
	};
	mediaRecorder.stop();
  });
}

export { startRecording, stopRecording };

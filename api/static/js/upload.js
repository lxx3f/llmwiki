// Simple chunked upload for TUS protocol
async function handleUpload(input, kbId) {
    const file = input.files[0];
    if (!file) return;

    const progress = document.getElementById('upload-progress');
    const bar = document.getElementById('upload-bar');
    const text = document.getElementById('upload-text');
    progress.classList.remove('hidden');
    text.textContent = 'Starting...';

    // Encode each value to base64, but NOT the whole header
    const enc = (s) => {
        const bytes = new TextEncoder().encode(s);
        let bin = '';
        bytes.forEach(b => bin += String.fromCharCode(b));
        return btoa(bin);
    };
    const metadata = `filename ${enc(file.name)},knowledge_base_id ${enc(kbId)}`;

    // Create upload
    const createResp = await fetch('/v1/uploads', {
        method: 'POST',
        headers: {
            'Tus-Resumable': '1.0.0',
            'Upload-Length': file.size.toString(),
            'Upload-Metadata': metadata,
        },
    });
    if (!createResp.ok) {
        text.textContent = 'Failed to create upload';
        return;
    }
    const location = createResp.headers.get('Location');

    // Upload in chunks
    const CHUNK = 1_048_576; // 1MB
    let offset = 0;

    while (offset < file.size) {
        const end = Math.min(offset + CHUNK, file.size);
        const chunk = file.slice(offset, end);

        const resp = await fetch(location, {
            method: 'PATCH',
            headers: {
                'Tus-Resumable': '1.0.0',
                'Content-Type': 'application/offset+octet-stream',
                'Upload-Offset': offset.toString(),
            },
            body: chunk,
        });

        if (resp.status === 204) {
            offset = parseInt(resp.headers.get('Upload-Offset') || end);
            const pct = Math.round(offset / file.size * 100);
            bar.style.width = pct + '%';
            text.textContent = `${pct}%`;

            const docId = resp.headers.get('X-Document-Id');
            if (docId) {
                text.textContent = 'Done! Processing...';
                setTimeout(() => location.reload(), 2000);
                return;
            }
        } else {
            text.textContent = 'Upload failed';
            return;
        }
    }
}

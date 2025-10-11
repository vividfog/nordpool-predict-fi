const narrationFile = window.location.pathname.includes('index_en') ? 'narration_en.md' : 'narration.md';

fetch(`${baseUrl}/${narrationFile}`)
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        return response.text();
    })
    .then(text => {
        document.getElementById('narration').innerHTML = marked.parse(text);
    })
    .catch(error => console.error('Fetching Markdown failed:', error));

function toggleClientInput() {
    const select = document.getElementById('clientSelect');
    const newClientInput = document.getElementById('newClientInput');
    newClientInput.style.display = select.value === 'new' ? 'block' : 'none';
}

function handleDrag(e) {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.classList.add('dragover');
}

function handleDragLeave(e) {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.classList.remove('dragover');
}

function handleFileDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.classList.remove('dragover');
    const files = Array.from(e.dataTransfer.files).filter(file => 
        file.name.match(/\.(txt|docx|html)$/i)
    );
    if (files.length === 0) {
        alert('Please upload only .txt, .docx, or .html files');
        return;
    }
    const input = document.getElementById('clientFiles');
    const dt = new DataTransfer();
    files.forEach(file => dt.items.add(file));
    input.files = dt.files;
    handleFileSelect({ target: input });
}

function handlePodcastDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.classList.remove('dragover');
    const files = e.dataTransfer.files;
    if (files.length > 0 && files[0].name.endsWith('.csv')) {
        const input = document.getElementById('podcastFile');
        input.files = files;
        handlePodcastSelect({ target: input });
    } else {
        alert('Please upload a CSV file');
    }
}

function handleFileSelect(e) {
    const files = e.target.files;
    const selectedFilesDiv = document.getElementById('selectedClientFiles');
    selectedFilesDiv.innerHTML = '';
    
    Array.from(files).forEach(file => {
        // Check allowed file types
        if (!file.name.match(/\.(txt|docx|html)$/i)) {
            alert('Please upload only .txt, .docx, or .html files');
            e.target.value = '';
            return;
        }

        const fileDiv = document.createElement('div');
        fileDiv.className = 'flex items-center space-x-2 text-sm text-gray-600 bg-gray-100 p-2 rounded';
        fileDiv.innerHTML = `
            <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                <path d="M4 4a2 2 0 012-2h8a2 2 0 012 2v12a2 2 0 01-2 2H6a2 2 0 01-2-2V4z"></path>
            </svg>
            <span>${file.name}</span>
            <button onclick="removeFile(this)" class="text-red-500 hover:text-red-700 ml-2" type="button">×</button>
        `;
        selectedFilesDiv.appendChild(fileDiv);
    });
}

function removeFile(button) {
    const fileDiv = button.parentElement;
    fileDiv.remove();
    const fileInput = document.getElementById('clientFiles');
    fileInput.value = '';
}

function handlePodcastSelect(e) {
    const file = e.target.files[0];
    const selectedFileDiv = document.getElementById('selectedPodcastFile');
    
    if (file && file.name.endsWith('.csv')) {
        selectedFileDiv.innerHTML = `
            <div class="flex items-center space-x-2 text-sm text-gray-600 bg-gray-100 p-2 rounded">
                <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M4 4a2 2 0 012-2h8a2 2 0 012 2v12a2 2 0 01-2 2H6a2 2 0 01-2-2V4z"></path>
                </svg>
                <span>${file.name}</span>
                <button onclick="removePodcastFile()" class="text-red-500 hover:text-red-700 ml-2" type="button">×</button>
            </div>
        `;
    } else {
        selectedFileDiv.innerHTML = '';
        alert('Please upload a CSV file');
        e.target.value = '';
    }
}

function removePodcastFile() {
    const selectedFileDiv = document.getElementById('selectedPodcastFile');
    selectedFileDiv.innerHTML = '';
    const fileInput = document.getElementById('podcastFile');
    fileInput.value = '';
}

function updateProgress(progressDiv, percentage) {
    const progressBar = progressDiv.querySelector('.progress-bar');
    const progressText = progressDiv.querySelector('span');
    progressBar.style.width = percentage + '%';
    progressText.textContent = percentage + '%';
}

async function showSuccessMessage(message) {
    const successMessage = document.getElementById('successMessage');
    successMessage.textContent = message;
    successMessage.classList.add('show');
    
    await new Promise(resolve => setTimeout(resolve, 3000));
    
    successMessage.classList.remove('show');
}

function updateClientDropdowns(clients) {
    const clientSelects = [
        document.getElementById('clientSelect'),
        document.getElementById('podcastClientSelect'),
        document.getElementById('matchingClientSelect')
    ];

    clientSelects.forEach(select => {
        const currentValue = select.value;
        select.innerHTML = '<option value="">Select a client</option>';
        
        clients.forEach(client => {
            const option = document.createElement('option');
            option.value = client.id;
            option.textContent = client.name;
            select.appendChild(option);
        });
        
        if (select.id === 'clientSelect') {
            const newOption = document.createElement('option');
            newOption.value = 'new';
            newOption.textContent = 'Add New Client';
            select.appendChild(newOption);
        }
        
        if (currentValue && select.querySelector(`option[value="${currentValue}"]`)) {
            select.value = currentValue;
        }
    });
}

document.addEventListener('DOMContentLoaded', function() {
    const clientForm = document.getElementById('clientForm');
    const podcastForm = document.getElementById('podcastForm');

    if (clientForm) {
        clientForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const form = e.target;
            const formData = new FormData(form);
            const progressDiv = document.getElementById('clientUploadProgress');

            try {
                progressDiv.classList.remove('hidden');
                let progress = 0;
                const interval = setInterval(() => {
                    progress += 5;
                    if (progress <= 90) {
                        updateProgress(progressDiv, progress);
                    }
                }, 300);

                const response = await fetch(form.action, {
                    method: 'POST',
                    body: formData
                });

                clearInterval(interval);
                updateProgress(progressDiv, 100);

                if (response.ok) {
                    const clientResponse = await fetch('/get_clients');
                    const clients = await clientResponse.json();
                    updateClientDropdowns(clients);
                    
                    setTimeout(() => {
                        progressDiv.classList.add('hidden');
                        updateProgress(progressDiv, 0);
                        showSuccessMessage("Client files uploaded successfully!");
                        document.getElementById('selectedClientFiles').innerHTML = '';
                        form.reset();
                    }, 500);
                } else {
                    throw new Error('Upload failed');
                }
            } catch (error) {
                alert('Error uploading files. Please try again.');
                progressDiv.classList.add('hidden');
                updateProgress(progressDiv, 0);
            }
        });
    }

    if (podcastForm) {
        podcastForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const form = e.target;
            const formData = new FormData(form);
            const progressDiv = document.getElementById('podcastUploadProgress');

            try {
                progressDiv.classList.remove('hidden');
                let progress = 0;
                const interval = setInterval(() => {
                    progress += 5;
                    if (progress <= 90) {
                        updateProgress(progressDiv, progress);
                    }
                }, 300);

                const response = await fetch(form.action, {
                    method: 'POST',
                    body: formData
                });

                clearInterval(interval);
                updateProgress(progressDiv, 100);

                if (response.ok) {
                    setTimeout(() => {
                        progressDiv.classList.add('hidden');
                        updateProgress(progressDiv, 0);
                        showSuccessMessage("Podcast data uploaded successfully!");
                        document.getElementById('selectedPodcastFile').innerHTML = '';
                        form.reset();
                    }, 500);
                } else {
                    throw new Error('Upload failed');
                }
            } catch (error) {
                alert('Error uploading file. Please try again.');
                progressDiv.classList.add('hidden');
                updateProgress(progressDiv, 0);
            }
        });
    }
});
function matchPodcasts() {
    const clientId = document.getElementById('matchingClientSelect').value;
    if (!clientId) {
        alert('Please select a client');
        return;
    }

    // Get selected listen score ranges
    const selectedRanges = Array.from(document.querySelectorAll('input[name="ls_range"]:checked'))
        .map(checkbox => checkbox.value);

    // Build query URL with selected ranges
    const queryParams = new URLSearchParams({
        client_id: clientId,
        ls_ranges: selectedRanges.join(',')
    });

    // Update active filters display
    updateActiveFilters(selectedRanges);

    // Show loading state
    document.getElementById('matchingResults').innerHTML = `
        <div class="flex items-center justify-center py-4">
            <svg class="animate-spin h-5 w-5 text-blue-500 mr-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <span class="text-gray-600">Matching podcasts...</span>
        </div>
    `;

    fetch(`/match_podcasts?${queryParams}`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                throw new Error(data.error);
            }
            displayPodcastMatches(data);
        })
        .catch(error => {
            console.error('Error:', error);
            document.getElementById('matchingResults').innerHTML = `
                <div class="text-red-500 mt-4">
                    Error: ${error.message}
                </div>
            `;
        });
}

function updateActiveFilters(selectedRanges) {
    const activeFiltersDiv = document.getElementById('activeFilters');
    if (selectedRanges.length > 0) {
        activeFiltersDiv.innerHTML = `
            <div class="text-sm text-gray-600 mt-2">
                Active Filters:
                ${selectedRanges.map(range => `
                    <span class="filter-badge">
                        LS: ${range}
                        <button onclick="removeFilter('${range}')" class="ml-1 focus:outline-none">
                            ×
                        </button>
                    </span>
                `).join('')}
            </div>
        `;
    } else {
        activeFiltersDiv.innerHTML = '';
    }
}

function removeFilter(range) {
    const checkbox = document.querySelector(`input[name="ls_range"][value="${range}"]`);
    if (checkbox) {
        checkbox.checked = false;
        matchPodcasts();
    }
}

function displayPodcastMatches(data) {
    const resultsDiv = document.getElementById('matchingResults');
    
    if (data.length === 0) {
        resultsDiv.innerHTML = `
            <div class="text-gray-600 mt-4">
                No matching podcasts found with the selected criteria.
            </div>
        `;
        return;
    }

    let html = `
        <div class="overflow-x-auto mt-4">
            <table class="min-w-full bg-white border border-gray-300 shadow-sm rounded-lg overflow-hidden">
                <thead class="bg-gray-50">
                    <tr class="text-xs md:text-sm">
                        <th class="px-4 py-2 border-b text-left">Podcast Name</th>
                        <th class="px-4 py-2 border-b text-center">Relevance Score</th>
                        <th class="px-4 py-2 border-b text-center">Audience Score</th>
                        <th class="px-4 py-2 border-b text-center">Guest Fit Score</th>
                        <th class="px-4 py-2 border-b text-center">Recency Score</th>
                        <th class="px-4 py-2 border-b text-center">Host Interest Score</th>
                        <th class="px-4 py-2 border-b text-center">Aggregate Score</th>
                        <th class="px-4 py-2 border-b text-left">Reason</th>
                        <th class="px-4 py-2 border-b text-left">Potential Mismatch</th>
                    </tr>
                </thead>
                <tbody>
    `;

    data.forEach(podcast => {
        const getScoreColor = (score) => {
            if (score >= 90) return 'text-green-600 font-bold';
            if (score >= 75) return 'text-green-500';
            if (score >= 60) return 'text-yellow-600';
            return 'text-red-500';
        };

        html += `
            <tr class="text-xs md:text-sm hover:bg-gray-50">
                <td class="px-4 py-2 border-b">${podcast.podcast_name}</td>
                <td class="px-4 py-2 border-b text-center ${getScoreColor(podcast.relevance_score)}">${podcast.relevance_score}</td>
                <td class="px-4 py-2 border-b text-center ${getScoreColor(podcast.audience_score)}">${podcast.audience_score}</td>
                <td class="px-4 py-2 border-b text-center ${getScoreColor(podcast.guest_fit_score)}">${podcast.guest_fit_score}</td>
                <td class="px-4 py-2 border-b text-center ${getScoreColor(podcast.recency_score)}">${podcast.recency_score}</td>
                <td class="px-4 py-2 border-b text-center ${getScoreColor(podcast.host_interest_score)}">${podcast.host_interest_score}</td>
                <td class="px-4 py-2 border-b text-center font-bold ${getScoreColor(podcast.aggregate_score)}">${podcast.aggregate_score}</td>
                <td class="px-4 py-2 border-b text-left">
                    <div class="max-w-xs md:max-w-md lg:max-w-lg whitespace-normal">${podcast.reason}</div>
                </td>
                <td class="px-4 py-2 border-b text-left">
                    <div class="max-w-xs md:max-w-md lg:max-w-lg whitespace-normal">${podcast.potential_mismatch}</div>
                </td>
            </tr>
        `;
    });

    html += `
                </tbody>
            </table>
        </div>
    `;
    
    resultsDiv.innerHTML = html;
}
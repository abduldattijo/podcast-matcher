function matchPodcasts() {
    const clientId = document.getElementById('matchingClientSelect').value;
    if (!clientId) {
        alert('Please select a client');
        return;
    }

    fetch(`/match_podcasts?client_id=${clientId}`)
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

function displayPodcastMatches(data) {
    const resultsDiv = document.getElementById('matchingResults');
    
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
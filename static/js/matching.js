// Initialize event listeners and generate score options when document loads
document.addEventListener('DOMContentLoaded', function() {
    generateScoreOptions();
    
    // Add event listeners for score changes
    document.getElementById('minScore').addEventListener('change', validateScoreRange);
    document.getElementById('maxScore').addEventListener('change', validateScoreRange);

    // Add event listener for client selection
    const clientSelect = document.getElementById('matchingClientSelect');
    if (clientSelect) {
        clientSelect.addEventListener('change', () => {
            loadPodcastStats();
            clearMatchingResults();
        });
    }
});

// Generate score options for min and max select elements
function generateScoreOptions() {
    const minSelect = document.getElementById('minScore');
    const maxSelect = document.getElementById('maxScore');
    
    // Clear existing options
    minSelect.innerHTML = '';
    maxSelect.innerHTML = '';
    
    // Generate options from 20 to 100 in steps of 5
    for (let i = 20; i <= 100; i += 5) {
        const minOption = new Option(i.toString(), i.toString());
        const maxOption = new Option(i.toString(), i.toString());
        
        minSelect.add(minOption);
        maxSelect.add(new Option(i.toString(), i.toString()));
    }

    // Set default values
    minSelect.value = "20";
    maxSelect.value = "100";
}

// Validate that min score is not greater than max score
function validateScoreRange() {
    const minScore = parseInt(document.getElementById('minScore').value);
    const maxScore = parseInt(document.getElementById('maxScore').value);
    
    if (minScore > maxScore) {
        alert('Minimum score cannot be greater than maximum score');
        return false;
    }
    return true;
}

// Clear matching results
function clearMatchingResults() {
    document.getElementById('matchingResults').innerHTML = '';
    document.getElementById('activeFilters').innerHTML = '';
}

// Load podcast statistics
function loadPodcastStats() {
    const clientId = document.getElementById('matchingClientSelect').value;
    if (!clientId) {
        return;
    }

    const statsDiv = document.getElementById('podcastStats');
    statsDiv.innerHTML = `
        <div class="flex items-center justify-center py-4">
            <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
            <span class="ml-3 text-gray-600">Loading statistics...</span>
        </div>
    `;

    fetch(`/get_podcast_stats?client_id=${clientId}`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                throw new Error(data.error);
            }
            displayPodcastStats(data);
        })
        .catch(error => {
            console.error('Error:', error);
            statsDiv.innerHTML = `
                <div class="text-red-500 bg-red-50 p-4 rounded-md">
                    <p>Error loading statistics: ${error.message}</p>
                </div>
            `;
        });
}

// Display podcast statistics
function displayPodcastStats(stats) {
    const statsDiv = document.getElementById('podcastStats');
    statsDiv.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
            <div class="stats-card bg-white p-4 rounded-lg shadow">
                <h3 class="text-gray-500 text-sm font-medium">Total Podcasts</h3>
                <p class="text-2xl font-bold">${stats.total_podcasts}</p>
            </div>
            <div class="stats-card bg-white p-4 rounded-lg shadow">
                <h3 class="text-gray-500 text-sm font-medium">Average Listen Score</h3>
                <p class="text-2xl font-bold">${stats.avg_listen_score}</p>
            </div>
            <div class="stats-card bg-white p-4 rounded-lg shadow">
                <h3 class="text-gray-500 text-sm font-medium">High Performing (80+)</h3>
                <p class="text-2xl font-bold">${stats.high_performing}</p>
            </div>
            <div class="stats-card bg-white p-4 rounded-lg shadow">
                <h3 class="text-gray-500 text-sm font-medium">Recently Active</h3>
                <p class="text-2xl font-bold">${stats.recently_active}</p>
            </div>
        </div>
    `;
}

// Export matched podcasts
function exportMatches() {
    const clientId = document.getElementById('matchingClientSelect').value;
    if (!clientId) {
        alert('Please select a client');
        return;
    }

    window.location.href = `/export_matches?client_id=${clientId}`;
}

// Main function to match podcasts
function matchPodcasts() {
    const clientId = document.getElementById('matchingClientSelect').value;
    if (!clientId) {
        alert('Please select a client');
        return;
    }

    if (!validateScoreRange()) {
        return;
    }

    const minScore = document.getElementById('minScore').value;
    const maxScore = document.getElementById('maxScore').value;
    const includeBlank = document.getElementById('includeBlank').checked;

    // Build query URL with all parameters
    const queryParams = new URLSearchParams({
        client_id: clientId,
        min_score: minScore,
        max_score: maxScore,
        include_blank: includeBlank
    });

    // Update active filters display
    updateActiveFilters(minScore, maxScore, includeBlank);

    // Show loading state
    document.getElementById('matchingResults').innerHTML = `
        <div class="flex items-center justify-center py-8">
            <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
            <span class="ml-3 text-gray-600">Matching podcasts...</span>
        </div>
    `;

    // Fetch matching results
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
                <div class="text-red-500 bg-red-50 p-4 rounded-md">
                    <p class="font-semibold">Error:</p>
                    <p>${error.message}</p>
                </div>
            `;
        });
}

// Update the active filters display
function updateActiveFilters(minScore, maxScore, includeBlank) {
    const activeFiltersDiv = document.getElementById('activeFilters');
    const filters = [`Listen Score: ${minScore} - ${maxScore}`];
    
    if (includeBlank) {
        filters.push('Including blank scores');
    }

    activeFiltersDiv.innerHTML = `
        <div class="text-sm text-gray-600">
            <span class="font-medium">Active Filters:</span>
            ${filters.map(filter => `
                <span class="inline-block bg-blue-100 text-blue-800 px-2 py-1 rounded mx-1">
                    ${filter}
                </span>
            `).join('')}
        </div>
    `;
}

// Display the matching results in a table
function displayPodcastMatches(data) {
    const resultsDiv = document.getElementById('matchingResults');
    
    if (data.length === 0) {
        resultsDiv.innerHTML = `
            <div class="text-gray-600 bg-gray-50 p-4 rounded-md text-center">
                No matching podcasts found with the selected criteria.
            </div>
        `;
        return;
    }

    let html = `
        <div class="mt-4 mb-4">
            <button onclick="exportMatches()" 
                    class="export-button bg-green-500 hover:bg-green-600 text-white font-bold py-2 px-4 rounded focus:outline-none focus:shadow-outline">
                Export Results
            </button>
        </div>
        <div class="overflow-x-auto">
            <table class="min-w-full bg-white border border-gray-300 shadow-sm rounded-lg overflow-hidden">
                <thead class="bg-gray-50">
                    <tr>
                        <th class="px-4 py-3 border-b border-gray-200 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                            Podcast Name
                        </th>
                        <th class="px-4 py-3 border-b border-gray-200 text-center text-xs font-semibold text-gray-600 uppercase tracking-wider">
                            Relevance Score
                        </th>
                        <th class="px-4 py-3 border-b border-gray-200 text-center text-xs font-semibold text-gray-600 uppercase tracking-wider">
                            Audience Score
                        </th>
                        <th class="px-4 py-3 border-b border-gray-200 text-center text-xs font-semibold text-gray-600 uppercase tracking-wider">
                            Guest Fit Score
                        </th>
                        <th class="px-4 py-3 border-b border-gray-200 text-center text-xs font-semibold text-gray-600 uppercase tracking-wider">
                            Recency Score
                        </th>
                        <th class="px-4 py-3 border-b border-gray-200 text-center text-xs font-semibold text-gray-600 uppercase tracking-wider">
                            Host Interest Score
                        </th>
                        <th class="px-4 py-3 border-b border-gray-200 text-center text-xs font-semibold text-gray-600 uppercase tracking-wider">
                            Aggregate Score
                        </th>
                        <th class="px-4 py-3 border-b border-gray-200 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                            Reason
                        </th>
                        <th class="px-4 py-3 border-b border-gray-200 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                            Potential Mismatch
                        </th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-gray-200">
    `;

    data.forEach((podcast, index) => {
        const getScoreColor = (score) => {
            if (score >= 90) return 'text-green-600 font-bold';
            if (score >= 75) return 'text-green-500';
            if (score >= 60) return 'text-yellow-600';
            return 'text-red-500';
        };

        const rowClass = index % 2 === 0 ? 'bg-white' : 'bg-gray-50';

        html += `
            <tr class="${rowClass} hover:bg-gray-100 transition-colors duration-150">
                <td class="px-4 py-3 text-sm">
                    <div class="font-medium text-gray-900">${podcast.podcast_name}</div>
                </td>
                <td class="px-4 py-3 text-sm text-center ${getScoreColor(podcast.relevance_score)}">
                    ${podcast.relevance_score.toFixed(1)}
                </td>
                <td class="px-4 py-3 text-sm text-center ${getScoreColor(podcast.audience_score)}">
                    ${podcast.audience_score.toFixed(1)}
                </td>
                <td class="px-4 py-3 text-sm text-center ${getScoreColor(podcast.guest_fit_score)}">
                    ${podcast.guest_fit_score.toFixed(1)}
                </td>
                <td class="px-4 py-3 text-sm text-center ${getScoreColor(podcast.recency_score)}">
                    ${podcast.recency_score.toFixed(1)}
                </td>
                <td class="px-4 py-3 text-sm text-center ${getScoreColor(podcast.host_interest_score)}">
                    ${podcast.host_interest_score.toFixed(1)}
                </td>
                <td class="px-4 py-3 text-sm text-center font-bold ${getScoreColor(podcast.aggregate_score)}">
                    ${podcast.aggregate_score.toFixed(1)}
                </td>
                <td class="px-4 py-3 text-sm">
                    <div class="max-w-xs md:max-w-md lg:max-w-lg whitespace-normal">
                        ${podcast.reason}
                    </div>
                </td>
                <td class="px-4 py-3 text-sm">
                    <div class="max-w-xs md:max-w-md lg:max-w-lg whitespace-normal text-gray-600">
                        ${podcast.potential_mismatch}
                    </div>
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

// Helper function to format numbers with commas
function numberWithCommas(x) {
    return x.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

// Helper function to create a tooltip element
function createTooltip(text) {
    return `
        <div class="group relative inline-block">
            <svg class="h-4 w-4 text-gray-400 ml-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div class="absolute bottom-full left-1/2 transform -translate-x-1/2 invisible group-hover:visible bg-gray-900 text-white text-sm rounded py-1 px-2 w-48 text-center">
                ${text}
            </div>
        </div>
    `;
}

// Export functions for potential use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        matchPodcasts,
        validateScoreRange,
        generateScoreOptions,
        updateActiveFilters,
        displayPodcastMatches,
        loadPodcastStats,
        exportMatches
    };
}
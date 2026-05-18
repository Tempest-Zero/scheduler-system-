// Configuration
const userId = 'demo_user';
let sessionId = 'session_' + Date.now();

// State
let extractedData = null;
let scheduleData = null;

// DOM elements
const rantInput = document.getElementById('rantInput');
const generateBtn = document.getElementById('generateBtn');
const followUpDiv = document.getElementById('followUp');
const extractedSection = document.getElementById('extractedSection');
const extractedTasks = document.getElementById('extractedTasks');
const scheduleSection = document.getElementById('scheduleSection');
const scheduleDisplay = document.getElementById('scheduleDisplay');
const feedbackSection = document.getElementById('feedbackSection');

// Escape text before inserting into innerHTML. Task names and reasons come
// from user input via an LLM, so they must never be trusted as markup.
function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
}

async function generateSchedule() {
    const text = rantInput.value.trim();
    if (!text) return;

    // BUG-009 fix: Only reset session if starting fresh (no follow-up in progress)
    if (followUpDiv.classList.contains('hidden')) {
        // New conversation - reset session
        sessionId = 'session_' + Date.now();
    }
    // Else: continue existing session for follow-up

    generateBtn.disabled = true;
    generateBtn.textContent = 'Processing...';

    try {
        // Step 1: Extract
        const extractRes = await fetch('/api/extract', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, session_id: sessionId, user_id: userId })
        });

        if (!extractRes.ok) {
            throw new Error(`Server error: ${extractRes.status}`);
        }

        const extractData = await extractRes.json();

        if (extractData.status === 'incomplete') {
            showFollowUp(extractData.follow_up);
            return;
        }

        if (extractData.status === 'error') {
            alert('Error: ' + extractData.error);
            return;
        }

        extractedData = extractData;
        hideFollowUp();
        showExtractedTasks(extractData);

        // Step 2: Generate schedule
        const scheduleRes = await fetch('/api/schedule', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...extractData, user_id: userId })
        });

        if (!scheduleRes.ok) {
            throw new Error(`Scheduler error: ${scheduleRes.status}`);
        }

        scheduleData = await scheduleRes.json();

        if (scheduleData.status === 'infeasible') {
            alert('Could not generate schedule: ' + scheduleData.error);
            return;
        }

        showSchedule(scheduleData);
        feedbackSection.classList.remove('hidden');

    } catch (err) {
        // BUG-020 fix: Better error handling
        console.error('Full error:', err);
        if (err.name === 'TypeError' && err.message.includes('fetch')) {
            alert('Network error - please check your connection and try again.');
        } else {
            alert('Error: ' + err.message);
        }
    } finally {
        generateBtn.disabled = false;
        generateBtn.textContent = 'Generate Schedule';
    }
}

function showFollowUp(message) {
    // Clear the input and set helpful placeholder
    rantInput.value = '';
    rantInput.placeholder = 'Answer the questions above... (e.g., "Prompts take 1 hour, slides 30 min, test 2 hours. I wake up at 8am.")';
    rantInput.focus();

    // Show follow-up questions with clear styling
    followUpDiv.innerHTML = `
        <div style="margin-bottom: 10px;">
            <strong>📋 Need a bit more info:</strong>
        </div>
        <div style="background: rgba(0,0,0,0.2); padding: 10px; border-radius: 8px; margin-bottom: 10px;">
            ${escapeHtml(message).replace(/\n/g, '<br>').replace(/• /g, '<br>• ')}
        </div>
        <div style="font-size: 0.9em; color: #aaa;">
            👇 Type your answers below and click "Generate Schedule" again
        </div>
    `;
    followUpDiv.classList.remove('hidden');
}

function hideFollowUp() {
    followUpDiv.classList.add('hidden');
}

function showExtractedTasks(data) {
    extractedSection.classList.remove('hidden');

    // Show time window if available
    const timeWindow = document.getElementById('timeWindow');
    if (data.wake_time && data.sleep_time) {
        timeWindow.innerHTML = `<strong>Time Window:</strong> ${data.wake_time} - ${data.sleep_time}`;
        timeWindow.style.display = 'block';
    } else {
        timeWindow.style.display = 'none';
    }

    let html = '';

    // Tasks
    for (const task of data.tasks) {
        const vagueClass = task.is_vague ? 'vague' : '';
        html += `
            <div class="task-card priority-${escapeHtml(task.priority)} ${vagueClass}">
                <div class="task-info">
                    <span class="task-name">${escapeHtml(task.name)}</span>
                    <span class="task-meta">${escapeHtml(task.hours)}h | ${escapeHtml(task.priority)} | ${escapeHtml(task.difficulty)}</span>
                </div>
                <span class="task-meta">Due: ${escapeHtml(task.deadline)}</span>
            </div>
        `;
    }

    // Fixed slots
    for (const slot of data.fixed_slots || []) {
        html += `
            <div class="task-card fixed-slot">
                <div class="task-info">
                    <span class="task-name">${escapeHtml(slot.name)}</span>
                    <span class="task-meta">Fixed</span>
                </div>
                <span class="task-meta">${escapeHtml(slot.start)} - ${escapeHtml(slot.end)}</span>
            </div>
        `;
    }

    extractedTasks.innerHTML = html;
}

function showSchedule(data) {
    scheduleSection.classList.remove('hidden');

    let html = '';

    // Show overflow warning if partial
    if (data.status === 'partial' && data.overflow_tasks?.length > 0) {
        html += `
            <div class="overflow-warning">
                <strong>Moved to tomorrow:</strong> ${data.overflow_tasks.join(', ')}
                <p class="overflow-reason">${data.error || 'Not enough time today'}</p>
            </div>
        `;
    }

    for (const item of data.schedule) {
        html += `
            <div class="schedule-item">
                <div class="time-block">
                    ${escapeHtml(item.start)}<br>
                    <small>${escapeHtml(item.end)}</small>
                </div>
                <div class="task-block">
                    <div>
                        <div class="task-name">${escapeHtml(item.task)}</div>
                        <div class="reason">${escapeHtml(item.reason)}</div>
                    </div>
                    <div class="task-actions">
                        <button class="move-later-btn" data-task="${escapeHtml(item.task)}" data-start="${escapeHtml(item.start)}">Move Later</button>
                    </div>
                </div>
            </div>
        `;
    }

    scheduleDisplay.innerHTML = html;
}

// Delegated handler: avoids inline onclick with string interpolation, which
// breaks on task names containing quotes and is an injection vector.
scheduleDisplay.addEventListener('click', (event) => {
    const btn = event.target.closest('.move-later-btn');
    if (btn) {
        moveLater(btn.dataset.task, btn.dataset.start);
    }
});

async function moveLater(taskName, currentTime) {
    const newTime = prompt(`Move "${taskName}" to what time? (e.g., 19:00)`);
    if (!newTime) return;

    try {
        const response = await fetch('/api/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: 'demo_user',
                task_name: taskName,
                action: 'move',
                from_time: currentTime,
                to_time: newTime
            })
        });

        const result = await response.json();

        if (result.ok) {
            alert(`Got it! I'll remember you prefer "${taskName}" at ${newTime}.`);

            // Handle should_reschedule - regenerate schedule with updated patterns
            if (result.should_reschedule && extractedData) {
                if (confirm('Regenerate schedule with your updated preference?')) {
                    await regenerateSchedule();
                }
            }
        }
    } catch (err) {
        console.error('Feedback error:', err);
    }
}

async function regenerateSchedule() {
    if (!extractedData) return;

    try {
        const scheduleRes = await fetch('/api/schedule', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...extractedData, user_id: userId })
        });
        scheduleData = await scheduleRes.json();

        if (scheduleData.status === 'infeasible') {
            alert('Could not regenerate schedule: ' + scheduleData.error);
            return;
        }

        showSchedule(scheduleData);
    } catch (err) {
        console.error('Regenerate error:', err);
    }
}

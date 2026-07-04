document.addEventListener('DOMContentLoaded', function () {
  var sidebar = document.getElementById('chatbot-sidebar');
  var toggleBtn = document.getElementById('chatbot-toggle-btn');
  var closeBtn = document.getElementById('chatbot-close-btn');
  var clearBtn = document.getElementById('chatbot-clear-btn');
  var form = document.getElementById('chatbot-form');
  var input = document.getElementById('chatbot-input');
  var messagesContainer = document.getElementById('chatbot-messages-container');

  if (!sidebar || !toggleBtn) return;

  var conversationHistory = [];
  var MAX_CHAT_HISTORY = 50;

  // Restore state
  var savedWidth = localStorage.getItem('chatbot-sidebar-width') || '420';
  sidebar.style.width = savedWidth + 'px';

  var isOpen = localStorage.getItem('chatbot-sidebar-open') === 'true';
  if (isOpen) {
    sidebar.classList.add('open');
  }

  var cachedHistory = localStorage.getItem('chatbot-conversation-history');
  if (cachedHistory) {
    try {
      conversationHistory = JSON.parse(cachedHistory);
      if (conversationHistory.length > MAX_CHAT_HISTORY) {
        conversationHistory = conversationHistory.slice(-MAX_CHAT_HISTORY);
      }
      renderSavedMessages();
    } catch (e) {
      conversationHistory = [];
    }
  }

  // Toggle
  toggleBtn.addEventListener('click', function () {
    sidebar.classList.toggle('open');
    localStorage.setItem('chatbot-sidebar-open', sidebar.classList.contains('open'));
    if (sidebar.classList.contains('open')) {
      input.focus();
      scrollToBottom();
    }
  });

  if (closeBtn) {
    closeBtn.addEventListener('click', function () {
      sidebar.classList.remove('open');
      localStorage.setItem('chatbot-sidebar-open', 'false');
    });
  }

  // Clear conversation
  if (clearBtn) {
    clearBtn.addEventListener('click', function () {
      if (confirm('¿Deseas vaciar el historial de la conversación actual?')) {
        conversationHistory = [];
        localStorage.removeItem('chatbot-conversation-history');
        var welcomeCard = messagesContainer.querySelector('.chatbot-welcome-card');
        messagesContainer.innerHTML = '';
        if (welcomeCard) {
          messagesContainer.appendChild(welcomeCard);
        }
      }
    });
  }

  // Predefined chips
  document.querySelectorAll('.chatbot-chip').forEach(function (chip) {
    chip.addEventListener('click', function () {
      input.value = this.textContent;
      form.dispatchEvent(new Event('submit'));
    });
  });

  // Submit
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var userText = input.value.trim();
    if (!userText) return;

    appendMessage('user', userText);
    input.value = '';

    var typingBubble = appendTypingIndicator();
    scrollToBottom();

    fetch('/api/chatbot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: userText,
        history: conversationHistory
      })
    })
    .then(function (res) { return res.json(); })
    .then(function (data) {
      typingBubble.remove();
      if (data.success) {
        appendMessage('ai', data.message);
        conversationHistory.push({ role: 'user', content: userText });
        conversationHistory.push({ role: 'assistant', content: data.message });
        if (conversationHistory.length > MAX_CHAT_HISTORY) {
          conversationHistory = conversationHistory.slice(-MAX_CHAT_HISTORY);
        }
        localStorage.setItem('chatbot-conversation-history', JSON.stringify(conversationHistory));
      } else {
        appendMessage('ai', data.message || 'Lo siento, ha ocurrido un error al procesar tu solicitud.');
      }
      scrollToBottom();
    })
    .catch(function () {
      typingBubble.remove();
      appendMessage('ai', '❌ **Error de comunicación.**\n\nNo he podido conectarme con el servidor. Revisa tu conexión a internet o el estado del sistema.');
      scrollToBottom();
    });
  });

  // Render functions
  function appendMessage(role, text) {
    var messageDiv = document.createElement('div');
    messageDiv.className = 'chatbot-message ' + (role === 'user' ? 'user' : 'ai');

    var timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    var formattedText = parseMarkdown(text);

    // Make links open in new tab
    formattedText = formattedText.replace(/<a\s+href=/g, '<a target="_blank" rel="noopener" href=');

    messageDiv.innerHTML =
      '<div class="chatbot-bubble">' + formattedText + '</div>' +
      '<div class="chatbot-meta">' + (role === 'user' ? 'Tú' : (window.PRODUCT_NAME || 'VykOne') + ' IA') + ' • ' + timeStr + '</div>';

    messagesContainer.appendChild(messageDiv);
    return messageDiv;
  }

  function appendTypingIndicator() {
    var div = document.createElement('div');
    div.className = 'chatbot-typing-bubble';
    div.innerHTML =
      '<div class="chatbot-typing-dot"></div>' +
      '<div class="chatbot-typing-dot"></div>' +
      '<div class="chatbot-typing-dot"></div>';
    messagesContainer.appendChild(div);
    return div;
  }

  function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  function renderSavedMessages() {
    if (conversationHistory.length > 0) {
      conversationHistory.forEach(function (item) {
        var role = item.role === 'assistant' ? 'ai' : 'user';
        appendMessage(role, item.content);
      });
    }
  }

  // Markdown parser
  function parseMarkdown(mdText) {
    if (!mdText) return '';

    var cleanText = mdText.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    var lines = cleanText.split('\n');
    var inList = false;
    var inOrderedList = false;
    var inCodeBlock = false;
    var inTable = false;
    var tableBuffer = [];
    var parsedLines = [];

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      var trimmed = line.trim();

      if (trimmed.startsWith('```')) {
        if (inCodeBlock) {
          parsedLines.push('</code></pre>');
          inCodeBlock = false;
        } else {
          parsedLines.push('<pre style="background: rgba(0,0,0,0.04); padding: 10px; border-radius: 6px; border: 1px solid var(--border-color); overflow-x: auto; margin: 6px 0; font-size: 0.8rem;"><code>');
          inCodeBlock = true;
        }
        continue;
      }

      if (inCodeBlock) {
        parsedLines.push(line);
        continue;
      }

      // Tables
      if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
        tableBuffer.push(trimmed);
        inTable = true;
        continue;
      }
      if (inTable) {
        parsedLines.push(buildTableHtml(tableBuffer));
        tableBuffer = [];
        inTable = false;
      }

      // Bold
      line = line.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      // Inline code
      line = line.replace(/`([^`]+)`/g, '<code>$1</code>');
      // Links: [text](url)
      line = line.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

      // Headers
      if (trimmed.startsWith('### ')) {
        parsedLines.push('<h5 style="margin: 10px 0 4px 0; font-weight: 700; color: var(--text-primary);">' + trimmed.substring(4) + '</h5>');
        continue;
      } else if (trimmed.startsWith('## ') || trimmed.startsWith('# ')) {
        var headerText = trimmed.startsWith('## ') ? trimmed.substring(3) : trimmed.substring(2);
        parsedLines.push('<h5 style="margin: 12px 0 6px 0; font-weight: 700; color: var(--accent-emerald);">' + headerText + '</h5>');
        continue;
      }

      // Bullet lists
      var bulletMatch = line.match(/^\s*[-*•]\s+(.+)$/);
      if (bulletMatch) {
        var content = bulletMatch[1];
        if (inOrderedList) { parsedLines.push('</ol>'); inOrderedList = false; }
        if (!inList) { parsedLines.push('<ul style="margin: 4px 0; padding-left: 18px;">'); inList = true; }
        parsedLines.push('<li style="margin-bottom: 2px;">' + content + '</li>');
        continue;
      }

      // Ordered lists
      var orderedMatch = line.match(/^\s*\d+\.\s+(.+)$/);
      if (orderedMatch) {
        var oContent = orderedMatch[1];
        if (inList) { parsedLines.push('</ul>'); inList = false; }
        if (!inOrderedList) { parsedLines.push('<ol style="margin: 4px 0; padding-left: 18px;">'); inOrderedList = true; }
        parsedLines.push('<li style="margin-bottom: 2px;">' + oContent + '</li>');
        continue;
      }

      // Close lists on empty lines
      if (inList && trimmed === '') { parsedLines.push('</ul>'); inList = false; }
      if (inOrderedList && trimmed === '') { parsedLines.push('</ol>'); inOrderedList = false; }

      parsedLines.push(line);
    }

    if (inList) parsedLines.push('</ul>');
    if (inOrderedList) parsedLines.push('</ol>');
    if (inTable) parsedLines.push(buildTableHtml(tableBuffer));
    if (inCodeBlock) parsedLines.push('</code></pre>');

    var html = parsedLines.join('\n');
    html = html.replace(/\n/g, '<br>');
    html = html.replace(/<\/table><br>/g, '</table>');
    html = html.replace(/<\/ul><br>/g, '</ul>');
    html = html.replace(/<\/ol><br>/g, '</ol>');
    html = html.replace(/<\/pre><br>/g, '</pre>');
    html = html.replace(/<li><br>/g, '<li>');
    html = html.replace(/<\/li><br>/g, '</li>');
    html = html.replace(/<br><br>/g, '<br>');

    return html;
  }

  function formatTableCell(text) {
    return text
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  }

  function buildTableHtml(rows) {
    rows = rows.filter(function(r) { return r.trim() !== ''; });
    if (rows.length < 2) return '<div>' + rows.join('<br>') + '</div>';

    var isSep = function(row) { return /^\|[\s\-:]+\|$/.test(row); };
    var splitRow = function(row) {
      return row.split('|').slice(1, -1).map(function(c) { return c.trim(); });
    };

    var html = '<div style="overflow-x: auto; margin: 6px 0;"><table style="width: 100%; border-collapse: collapse; font-size: 0.8rem;">';

    // Find header (first row after separator, or first row if no clear separator)
    var headerRow = null;
    var bodyStart = 0;
    if (rows.length >= 2 && isSep(rows[1])) {
      headerRow = splitRow(rows[0]);
      bodyStart = 2;
    } else {
      headerRow = splitRow(rows[0]);
      bodyStart = 1;
    }

    if (headerRow && headerRow.length > 0) {
      html += '<thead><tr>';
      headerRow.forEach(function(c) {
        html += '<th style="background: rgba(0,0,0,0.04); padding: 6px 8px; text-align: left; font-weight: 700; border-bottom: 2px solid var(--border-color); white-space: nowrap;">' + formatTableCell(c) + '</th>';
      });
      html += '</tr></thead>';
    }

    html += '<tbody>';
    for (var t = bodyStart; t < rows.length; t++) {
      if (isSep(rows[t])) continue;
      var cells = splitRow(rows[t]);
      if (cells.length === 0) continue;
      html += '<tr>';
      cells.forEach(function(c) {
        html += '<td style="padding: 5px 8px; border-bottom: 1px solid var(--border-color);">' + formatTableCell(c) + '</td>';
      });
      html += '</tr>';
    }
    html += '</tbody></table></div>';
    return html;
  }
});

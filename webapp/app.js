/* ======================================================================
IP Landscape Advanced Insight — Dataiku Standard Webapp "JavaScript" 탭.

렌더링 모듈 구성 (분석 로직은 전부 Python Backend):
  Api        — backend 호출 (getWebAppBackendUrl), Spinner/오류 Toast 공통 처리
  Ui         — escape/포맷/토스트/모달 유틸 (XSS 방지: 모든 데이터 문자열 esc())
  Filters    — 공통 필터 바 (기간/출원인/기술분류/국가/법적상태/유효특허)
  Render     — Plotly/Cytoscape/ECharts 렌더러 + PNG/SVG/Excel 다운로드 + Drill 클릭
  Insight    — 자동 인사이트 박스 (규칙 기반 + LLM 버튼, 면책문구 고정 표시)
  Drill      — 근거 특허 모달 (페이지네이션 + Excel)
  Views      — 메뉴별 화면 (Overview/Evolution/Competitor/WhiteSpace/Power/Quality/Settings)
====================================================================== */
(function () {
  'use strict';

  var backendUrl = (typeof getWebAppBackendUrl === 'function')
    ? getWebAppBackendUrl : function (p) { return p; };

  var State = {
    config: null,          // /api/config 응답
    filters: {},           // 현재 필터
    filterOptions: null,
    view: 'overview',
    lastResults: {},       // 분석명 → 응답 (가중치 재계산 등 재사용)
    settingsDraft: {}
  };

  /* ------------------------------------------------------------------ Api */
  var Api = (function () {
    var pending = 0;
    function spin(on, text) {
      pending += on ? 1 : -1;
      if (pending < 0) pending = 0;
      var el = document.getElementById('ipls-spinner');
      document.getElementById('spinner-text').textContent = text || '계산 중…';
      el.classList.toggle('hidden', pending === 0);
    }
    function handle(resp) {
      return resp.json().then(function (data) {
        if (data && data.status === 'error') { throw new Error(data.message || '오류'); }
        return data;
      });
    }
    return {
      get: function (path) {
        spin(true);
        return fetch(backendUrl(path)).then(handle)
          .finally(function () { spin(false); });
      },
      post: function (path, body, spinText) {
        spin(true, spinText);
        return fetch(backendUrl(path), {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body || {})
        }).then(handle).finally(function () { spin(false); });
      },
      download: function (path, body, filename) {
        spin(true, '파일 생성 중…');
        return fetch(backendUrl(path), {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body || {})
        }).then(function (resp) {
          if (!resp.ok) { return resp.json().then(function (d) { throw new Error(d.message || '다운로드 실패'); }); }
          return resp.blob();
        }).then(function (blob) {
          var a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = filename || 'export.xlsx';
          document.body.appendChild(a); a.click(); a.remove();
          setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
        }).finally(function () { spin(false); });
      }
    };
  })();

  /* ------------------------------------------------------------------- Ui */
  var Ui = {
    esc: function (s) {
      if (s === null || s === undefined) return '';
      return String(s).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
      });
    },
    num: function (v, d) {
      if (v === null || v === undefined || isNaN(v)) return '-';
      return Number(v).toLocaleString('ko-KR', { maximumFractionDigits: d === undefined ? 1 : d });
    },
    pct: function (v, d) {
      if (v === null || v === undefined || isNaN(v)) return '-';
      return (Number(v) * 100).toFixed(d === undefined ? 1 : d) + '%';
    },
    toast: function (msg, kind) {
      var box = document.createElement('div');
      box.className = 'toast' + (kind ? ' ' + kind : '');
      box.textContent = msg;
      document.getElementById('ipls-toasts').appendChild(box);
      setTimeout(function () { box.remove(); }, 5200);
    },
    el: function (html) {
      var t = document.createElement('template');
      t.innerHTML = html.trim();
      return t.content.firstChild;
    }
  };

  function errToast(e) { Ui.toast(e && e.message ? e.message : '요청 실패', 'error'); }

  /* -------------------------------------------------------------- Filters */
  var Filters = (function () {
    function fillSelect(id, values) {
      var sel = document.getElementById(id);
      sel.innerHTML = '';
      (values || []).forEach(function (v) {
        var o = document.createElement('option');
        o.value = v; o.textContent = v;
        sel.appendChild(o);
      });
    }
    function selected(id) {
      return Array.prototype.map.call(
        document.getElementById(id).selectedOptions, function (o) { return o.value; });
    }
    function collect() {
      var f = {};
      var yf = document.getElementById('f-year-from').value;
      var yt = document.getElementById('f-year-to').value;
      if (yf) f.year_from = Number(yf);
      if (yt) f.year_to = Number(yt);
      ['applicants|f-applicants', 'tech_l1|f-tech-l1', 'tech_l2|f-tech-l2',
       'tech_l3|f-tech-l3', 'countries|f-countries', 'legal_statuses|f-legal']
        .forEach(function (pair) {
          var parts = pair.split('|');
          var vals = selected(parts[1]);
          if (vals.length) f[parts[0]] = vals;
        });
      if (document.getElementById('f-active-only').checked) f.active_only = true;
      return f;
    }
    function restore(saved) {
      if (!saved) return;
      if (saved.year_from) document.getElementById('f-year-from').value = saved.year_from;
      if (saved.year_to) document.getElementById('f-year-to').value = saved.year_to;
      [['applicants', 'f-applicants'], ['tech_l1', 'f-tech-l1'], ['tech_l2', 'f-tech-l2'],
       ['tech_l3', 'f-tech-l3'], ['countries', 'f-countries'], ['legal_statuses', 'f-legal']]
        .forEach(function (pair) {
          var vals = saved[pair[0]] || [];
          Array.prototype.forEach.call(document.getElementById(pair[1]).options, function (o) {
            o.selected = vals.indexOf(o.value) >= 0;
          });
        });
      document.getElementById('f-active-only').checked = !!saved.active_only;
    }
    function load() {
      return Api.post('/api/filter-options', { filters: {} }).then(function (data) {
        State.filterOptions = data.options;
        fillSelect('f-applicants', data.options.applicants);
        fillSelect('f-tech-l1', data.options.tech_l1);
        fillSelect('f-tech-l2', data.options.tech_l2);
        fillSelect('f-tech-l3', data.options.tech_l3);
        fillSelect('f-countries', data.options.countries);
        fillSelect('f-legal', data.options.legal_statuses);
        var yf = document.getElementById('f-year-from');
        var yt = document.getElementById('f-year-to');
        yf.placeholder = data.options.year_min || 'from';
        yt.placeholder = data.options.year_max || 'to';
        document.getElementById('ipls-dataset-name').textContent =
          'Dataset: ' + (data.dataset || '-') + ' (' + Ui.num(data.n_rows, 0) + '건)';
        restore(State.config && State.config.filter_state);
        State.filters = collect();
      });
    }
    function apply() {
      State.filters = collect();
      Api.post('/api/filter-state', { filters: State.filters }).catch(function () {});
      Views.render(State.view);
    }
    function reset() {
      document.getElementById('f-year-from').value = '';
      document.getElementById('f-year-to').value = '';
      ['f-applicants', 'f-tech-l1', 'f-tech-l2', 'f-tech-l3', 'f-countries', 'f-legal']
        .forEach(function (id) {
          Array.prototype.forEach.call(document.getElementById(id).options,
            function (o) { o.selected = false; });
        });
      document.getElementById('f-active-only').checked = false;
      apply();
    }
    return { load: load, apply: apply, reset: reset, collect: collect };
  })();

  /* --------------------------------------------------------------- Render */
  var Render = (function () {
    function statusBlock(result) {
      if (result.status === 'empty') {
        return '<div class="status-empty">' + Ui.esc(result.message || '계산 불가: 데이터가 없습니다.') + '</div>';
      }
      if (result.status === 'disabled') {
        var cols = (result.missing_columns || []).map(Ui.esc).join(', ');
        return '<div class="status-disabled">' + Ui.esc(result.message || '필수 컬럼이 없습니다.') +
          (cols ? '<div class="cols">필요 컬럼: ' + cols + '</div>' : '') + '</div>';
      }
      return '<div class="status-error">' + Ui.esc(result.message || '오류가 발생했습니다.') + '</div>';
    }

    function plotly(holder, fig, onDrill) {
      Plotly.newPlot(holder, fig.data, fig.layout, {
        responsive: true, displaylogo: false,
        modeBarButtonsToRemove: ['lasso2d', 'select2d']
      });
      if (onDrill) {
        holder.on('plotly_click', function (ev) {
          var pt = ev.points && ev.points[0];
          if (!pt) return;
          var cd = pt.customdata;
          if (cd && cd.drill) onDrill(cd.drill, cd);
          else if (cd && cd.length && cd[0] && cd[0].drill) onDrill(cd[0].drill, cd[0]);
        });
      }
      return holder;
    }

    function cytoscape_(holder, network, opts) {
      opts = opts || {};
      var cy = cytoscape({
        container: holder,
        elements: network,
        layout: { name: 'cose', animate: false, nodeRepulsion: 9000, idealEdgeLength: 90 },
        style: [
          { selector: 'node', style: {
            'width': 'data(size)', 'height': 'data(size)',
            'background-color': 'data(color)', 'label': 'data(label)',
            'font-size': 9, 'text-valign': 'bottom', 'text-margin-y': 4,
            'border-width': 2, 'border-color': '#8899aa', 'text-wrap': 'ellipsis',
            'text-max-width': 90
          } },
          { selector: 'node[border_color]', style: { 'border-color': 'data(border_color)' } },
          { selector: 'edge', style: {
            'width': 'data(width)', 'line-color': 'data(color)', 'opacity': 0.75,
            'curve-style': 'bezier'
          } },
          { selector: 'edge[color]', style: { 'line-color': 'data(color)' } },
          { selector: 'edge[?arrow]', style: {
            'target-arrow-shape': 'triangle', 'target-arrow-color': 'data(color)'
          } },
          { selector: 'edge[label]', style: {
            'label': 'data(label)', 'font-size': 8, 'text-rotation': 'autorotate',
            'text-background-color': '#fff', 'text-background-opacity': 0.8
          } }
        ]
      });
      cy.on('tap', 'node', function (ev) {
        var d = ev.target.data();
        if (opts.onNode) opts.onNode(d);
        else if (d.drill) Drill.open(d.drill, d.label);
      });
      cy.on('tap', 'edge', function (ev) {
        var d = ev.target.data();
        if (opts.onEdge) opts.onEdge(d);
        else if (d.drill) Drill.open(d.drill, d.source + ' × ' + d.target);
      });
      return cy;
    }

    function echarts_(holder, option) {
      var chart = echarts.init(holder);
      chart.setOption(option);
      return chart;
    }

    function chartButtons(getTarget, baseName) {
      var wrap = Ui.el('<span class="card-controls"></span>');
      ['png', 'svg'].forEach(function (fmt) {
        var b = Ui.el('<button class="btn small">' + fmt.toUpperCase() + '</button>');
        b.addEventListener('click', function () {
          var t = getTarget();
          if (!t) return;
          try {
            if (t.kind === 'plotly') {
              Plotly.downloadImage(t.el, { format: fmt, filename: baseName, width: 1200, height: 700 });
            } else if (t.kind === 'cy') {
              if (fmt === 'svg') { Ui.toast('네트워크는 PNG 다운로드만 지원합니다.', 'warn'); return; }
              var a = document.createElement('a');
              a.href = t.cy.png({ full: true, scale: 2, bg: '#ffffff' });
              a.download = baseName + '.png';
              a.click();
            } else if (t.kind === 'echarts') {
              if (fmt === 'svg') { Ui.toast('대형 히트맵은 PNG 다운로드만 지원합니다.', 'warn'); return; }
              var a2 = document.createElement('a');
              a2.href = t.chart.getDataURL({ pixelRatio: 2, backgroundColor: '#fff' });
              a2.download = baseName + '.png';
              a2.click();
            }
          } catch (e) { errToast(e); }
        });
        wrap.appendChild(b);
      });
      return wrap;
    }

    function excelButton(drill, filename) {
      var b = Ui.el('<button class="btn small">Excel</button>');
      b.addEventListener('click', function () {
        Api.download('/api/export',
          { filters: State.filters, drill: drill || null, filename: filename },
          (filename || 'export') + '.xlsx').catch(errToast);
      });
      return b;
    }
    return { statusBlock: statusBlock, plotly: plotly, cytoscape: cytoscape_,
             echarts: echarts_, chartButtons: chartButtons, excelButton: excelButton };
  })();

  /* -------------------------------------------------------------- Insight */
  var Insight = (function () {
    function box(result, analysisName) {
      var ins = result.insight || { sentences: [] };
      var meta = result.meta || {};
      var div = Ui.el('<div class="insight-box"></div>');
      var src = Ui.el('<div class="insight-src">자동 인사이트 (' +
        (ins.source === 'llm' ? 'LLM' : '규칙 기반') + ')' +
        (meta.generated_at ? ' · 생성 ' + Ui.esc(meta.generated_at) : '') +
        (meta.cache_hit ? ' · 캐시' : '') + '</div>');
      div.appendChild(src);
      var ul = document.createElement('ul');
      (ins.sentences || []).forEach(function (s) {
        var li = document.createElement('li');
        li.textContent = s;
        ul.appendChild(li);
      });
      div.appendChild(ul);
      if (ins.llm_note) {
        div.appendChild(Ui.el('<div class="insight-src">' + Ui.esc(ins.llm_note) + '</div>'));
      }
      var drills = Ui.el('<div class="insight-drills"></div>');
      (ins.drills || []).forEach(function (d) {
        var b = Ui.el('<button class="btn small">' + Ui.esc(d.label) + ' →</button>');
        b.addEventListener('click', function () { Drill.open(d.drill, d.label); });
        drills.appendChild(b);
      });
      if (State.config && State.config.settings && State.config.settings.llm_insights_enabled) {
        var lb = Ui.el('<button class="btn small">LLM 인사이트 생성</button>');
        lb.addEventListener('click', function () {
          Api.post('/api/insight', {
            analysis: analysisName,
            metrics: ins.metrics || {},
            sentences: ins.sentences || []
          }, 'LLM 인사이트 생성 중…').then(function (data) {
            ul.innerHTML = '';
            (data.sentences || []).forEach(function (s) {
              var li = document.createElement('li');
              li.textContent = s;
              ul.appendChild(li);
            });
            src.textContent = '자동 인사이트 (' + (data.source === 'llm' ? 'LLM' : '규칙 기반(폴백)') + ')';
            if (data.llm_note) Ui.toast(data.llm_note, 'warn');
          }).catch(errToast);
        });
        drills.appendChild(lb);
      }
      div.appendChild(drills);
      if (meta.disclaimer) {
        div.appendChild(Ui.el('<div class="disclaimer">' + Ui.esc(meta.disclaimer) + '</div>'));
      }
      if (meta.note) {
        div.appendChild(Ui.el('<div class="disclaimer">' + Ui.esc(meta.note) + '</div>'));
      }
      return div;
    }

    function aiPanel(analysisName, result, description) {
      /* 그래프별 AI 인사이트 패널: 인사이트 요청 버튼 + 추가 질문 챗 입력창.
         요약 통계·규칙 문장만 서버로 전달하며, LLM 미가용 시 규칙 기반으로 폴백. */
      var ins = (result && result.insight) || { sentences: [], metrics: {} };
      var history = [];
      var panel = Ui.el(
        '<div class="ai-panel">' +
        '<div class="ai-head"><span class="ai-title">🤖 AI 인사이트</span>' +
        '<button class="btn small primary ai-ask">인사이트 요청</button></div>' +
        '<div class="chat-log"></div>' +
        '<div class="chat-wait" style="display:none">AI 응답 생성 중…</div>' +
        '<div class="chat-input-row">' +
        '<input type="text" placeholder="이 그래프에 대해 추가로 질문하세요… (예: 가장 위험한 영역은?)">' +
        '<button class="btn small">질문</button></div></div>');
      var log = panel.querySelector('.chat-log');
      var waitEl = panel.querySelector('.chat-wait');
      var input = panel.querySelector('.chat-input-row input');
      var sendBtn = panel.querySelector('.chat-input-row button');
      var askBtn = panel.querySelector('.ai-ask');

      function addMsg(role, text, source) {
        var m = Ui.el('<div class="chat-msg ' + role + '"></div>');
        m.textContent = text;
        if (role === 'assistant') {
          m.appendChild(Ui.el('<span class="chat-src">' +
            (source === 'llm' ? 'LLM 생성 (요약 통계 기반)' : '규칙 기반 폴백') + '</span>'));
        }
        log.appendChild(m);
        log.scrollTop = log.scrollHeight;
      }

      function ask(question) {
        if (question) {
          addMsg('user', question);
          history.push({ role: 'user', content: question });
        }
        waitEl.style.display = '';
        askBtn.disabled = true; sendBtn.disabled = true;
        Api.post('/api/insight', {
          analysis: analysisName, chat: true, question: question || null,
          history: history.slice(-8),
          metrics: ins.metrics || {}, sentences: ins.sentences || [],
          description: (description || '').slice(0, 500)
        }, 'AI 인사이트 생성 중…').then(function (d) {
          addMsg('assistant', d.answer || '(응답 없음)', d.source);
          history.push({ role: 'assistant', content: (d.answer || '').slice(0, 800) });
        }).catch(function (e) {
          addMsg('assistant', '요청 실패: ' + e.message, 'rule');
        }).finally(function () {
          waitEl.style.display = 'none';
          askBtn.disabled = false; sendBtn.disabled = false;
        });
      }
      askBtn.addEventListener('click', function () { ask(null); });
      function submit() {
        var q = input.value.trim();
        if (!q) return;
        input.value = '';
        ask(q);
      }
      sendBtn.addEventListener('click', submit);
      input.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter') submit();
      });
      return panel;
    }
    return { box: box, aiPanel: aiPanel };
  })();

  /* ---------------------------------------------------------------- Drill */
  var Drill = (function () {
    var current = { drill: null, page: 1, title: '' };
    function open(drill, title) {
      current = { drill: drill, page: 1, title: title || '근거 특허' };
      document.getElementById('modal-title').textContent = current.title;
      document.getElementById('ipls-modal').classList.remove('hidden');
      load();
    }
    function load() {
      Api.post('/api/patents', {
        filters: State.filters, drill: current.drill, page: current.page, page_size: 25
      }).then(function (data) {
        var body = document.getElementById('modal-body');
        if (!data.records || !data.records.length) {
          body.innerHTML = '<div class="status-empty">해당 조건의 특허가 없습니다.</div>';
          document.getElementById('modal-page-info').textContent = '0건';
          return;
        }
        var cols = Object.keys(data.records[0]);
        var html = '<table class="ipls-table"><thead><tr>' +
          cols.map(function (c) { return '<th>' + Ui.esc(c) + '</th>'; }).join('') +
          '</tr></thead><tbody>';
        data.records.forEach(function (r) {
          html += '<tr>' + cols.map(function (c) {
            return '<td>' + Ui.esc(r[c]) + '</td>';
          }).join('') + '</tr>';
        });
        html += '</tbody></table>';
        body.innerHTML = html;
        var pages = Math.max(1, Math.ceil(data.total / data.page_size));
        document.getElementById('modal-page-info').textContent =
          '총 ' + Ui.num(data.total, 0) + '건 · ' + data.page + '/' + pages + ' 페이지';
        document.getElementById('modal-prev').disabled = data.page <= 1;
        document.getElementById('modal-next').disabled = data.page >= pages;
      }).catch(errToast);
    }
    document.getElementById('modal-close').addEventListener('click', function () {
      document.getElementById('ipls-modal').classList.add('hidden');
    });
    document.getElementById('modal-prev').addEventListener('click', function () {
      if (current.page > 1) { current.page -= 1; load(); }
    });
    document.getElementById('modal-next').addEventListener('click', function () {
      current.page += 1; load();
    });
    document.getElementById('modal-export').addEventListener('click', function () {
      Api.download('/api/export', { filters: State.filters, drill: current.drill,
        filename: 'patents_' + Date.now() }, 'patents.xlsx').catch(errToast);
    });
    return { open: open };
  })();

  /* ----------------------------------------------------- 공통 카드 빌더 */
  function card(title, helpText) {
    // 설명(helpText)은 hover 툴팁이 아니라 카드 상단에 상시 표시한다.
    var c = Ui.el(
      '<div class="card"><div class="card-head"><span class="card-title">' + Ui.esc(title) +
      '</span><span class="card-controls"></span></div>' +
      (helpText ? '<div class="card-desc">' + Ui.esc(helpText) + '</div>' : '') +
      '<div class="card-body"></div></div>');
    return { root: c, controls: c.querySelector('.card-controls'),
             body: c.querySelector('.card-body'), desc: helpText || '' };
  }

  function simpleTable(headers, rows) {
    var html = '<table class="ipls-table"><thead><tr>' +
      headers.map(function (h) { return '<th>' + Ui.esc(h) + '</th>'; }).join('') +
      '</tr></thead><tbody>';
    rows.forEach(function (r) { html += '<tr>' + r + '</tr>'; });
    return html + '</tbody></table>';
  }

  function drillCell(label, drill) {
    var span = Ui.el('<span class="clickable">' + Ui.esc(label) + '</span>');
    span.addEventListener('click', function () { Drill.open(drill, label); });
    return span;
  }

  /* ---------------------------------------------------------------- Views */
  var Views = {};

  Views.render = function (view) {
    State.view = view;
    document.querySelectorAll('#ipls-menu li').forEach(function (li) {
      li.classList.toggle('active', li.getAttribute('data-view') === view);
    });
    var content = document.getElementById('ipls-content');
    content.innerHTML = '';
    (Views[view] || Views.overview)(content);
  };

  function makeTabs(content, tabs) {
    var bar = Ui.el('<div class="view-tabs"></div>');
    var holder = Ui.el('<div></div>');
    content.appendChild(bar);
    content.appendChild(holder);
    tabs.forEach(function (t, i) {
      var b = Ui.el('<button>' + Ui.esc(t.label) + '</button>');
      b.addEventListener('click', function () {
        bar.querySelectorAll('button').forEach(function (x) { x.classList.remove('active'); });
        b.classList.add('active');
        holder.innerHTML = '';
        t.render(holder);
      });
      bar.appendChild(b);
      if (i === 0) { b.classList.add('active'); t.render(holder); }
    });
  }

  function availabilityGuard(analysis, holder) {
    var avail = State.config && State.config.availability && State.config.availability[analysis];
    if (avail && !avail.available) {
      holder.innerHTML = '<div class="status-disabled">필수 컬럼이 없어 이 분석은 비활성화되었습니다.' +
        '<div class="cols">필요 컬럼: ' + avail.missing.map(Ui.esc).join(', ') +
        '</div><div class="cols">Settings → 컬럼 매핑에서 매핑하세요.</div></div>';
      return false;
    }
    return true;
  }

  /* ---------- 1. Executive Overview ---------- */
  Views.overview = function (content) {
    var c = card('Executive Overview', '기술·경쟁·권리 신호 요약. KPI 카드와 목록 클릭 시 근거 특허/상세 메뉴로 이동합니다.');
    content.appendChild(c.root);
    if (!availabilityGuard('overview', c.body)) return;
    Api.post('/api/overview', { filters: State.filters }, 'Overview 계산 중…').then(function (r) {
      State.lastResults.overview = r;
      if (r.status !== 'ok') { c.body.innerHTML = Render.statusBlock(r); return; }
      c.body.innerHTML = '';
      var k = r.kpi;
      var kpis = [
        { v: Ui.num(k.total, 0), l: '분석 문헌 수', view: null },
        { v: k.families !== null ? Ui.num(k.families, 0) : '-', l: '패밀리 수', view: null },
        { v: Ui.num(k.applicants, 0), l: '출원인 수', view: 'competitor' },
        { v: k.countries !== null ? Ui.num(k.countries, 0) : '-', l: '국가 수', view: null },
        { v: k.active_share !== null ? Ui.pct(k.active_share) : '-', l: '유효특허 비율', view: 'power' },
        { v: (k.year_min || '-') + '–' + (k.year_max || '-'), l: '분석 기간', view: null }
      ];
      var grid = Ui.el('<div class="kpi-grid"></div>');
      kpis.forEach(function (x) {
        var el = Ui.el('<div class="kpi"><div class="kpi-value">' + Ui.esc(x.v) +
          '</div><div class="kpi-label">' + Ui.esc(x.l) + '</div></div>');
        if (x.view) el.addEventListener('click', function () { Views.render(x.view); });
        grid.appendChild(el);
      });
      c.body.appendChild(grid);

      var lists = Ui.el('<div class="list-grid" style="margin-top:12px"></div>');
      function listCard(title, rows, view) {
        var lc = card(title);
        if (view) {
          var goBtn = Ui.el('<button class="btn small">상세 →</button>');
          goBtn.addEventListener('click', function () { Views.render(view); });
          lc.controls.appendChild(goBtn);
        }
        lc.body.innerHTML = '';
        if (!rows.length) { lc.body.innerHTML = '<div class="status-empty">해당 없음</div>'; }
        rows.forEach(function (row) { lc.body.appendChild(row); });
        lists.appendChild(lc.root);
      }
      function rowEl(main, drill, extra) {
        var d = Ui.el('<div style="display:flex;justify-content:space-between;gap:8px;' +
          'padding:4px 0;border-bottom:1px solid #f0f4f7"></div>');
        d.appendChild(drill ? drillCell(main, drill) : Ui.el('<span>' + Ui.esc(main) + '</span>'));
        d.appendChild(Ui.el('<span style="color:#647b8d;white-space:nowrap">' + extra + '</span>'));
        return d;
      }
      listCard('성장 기술 Top 10', r.growing.map(function (g) {
        return rowEl(g.tech, g.drill, Ui.pct(g.growth) + ' · ' + Ui.num(g.recent, 0) + '건');
      }), 'evolution');
      listCard('쇠퇴 기술 Top 10', r.declining.map(function (g) {
        return rowEl(g.tech, g.drill, Ui.pct(g.growth) + ' · 누적 ' + Ui.num(g.total, 0) + '건');
      }), 'evolution');
      listCard('신규 기술조합 Top 10', r.new_combos.map(function (g) {
        return rowEl(g.a + ' × ' + g.b, g.drill,
          g.first_year + '년 최초 · ' + Ui.num(g.count, 0) + '건 · 신규 ' + g.new_applicants + '개사');
      }), 'evolution');
      listCard('경쟁사 전략변화 Top 5', r.strategy_changes.map(function (g) {
        return rowEl(g.company, g.drill, '변화 ' + Ui.num(g.change, 3) + ' · → ' + Ui.esc(g.top_shift));
      }), 'competitor');
      listCard('권리장벽 높은 영역', r.barriers.map(function (g) {
        return rowEl(g.tech, g.drill, '유효등록 ' + Ui.num(g.active_granted, 0) + ' · CR3 ' + Ui.pct(g.cr3));
      }), 'power');
      listCard('진입 가능 공백영역', r.whitespace.map(function (g) {
        return rowEl(g.tech, g.drill, '성장 ' + Ui.pct(g.growth) + ' · CR3 ' + Ui.pct(g.cr3));
      }), 'whitespace');
      var alertRows = [];
      (r.alerts.key_patents || []).forEach(function (a) {
        alertRows.push(rowEl('🔑 ' + a.id + ' ' + a.title,
          { type: 'ids', ids: [a.id] }, '피인용 ' + a.cites));
      });
      (r.alerts.expiring || []).forEach(function (a) {
        alertRows.push(rowEl('⏳ ' + a.id + ' ' + a.title, { type: 'ids', ids: [a.id] },
          '만료 ' + a.expiry));
      });
      (r.alerts.key_companies || []).forEach(function (a) {
        alertRows.push(rowEl('🏢 ' + a.company, a.drill,
          '피인용합 ' + Ui.num(a.total_cites, 0) + ' · ' + Ui.num(a.patents, 0) + '건'));
      });
      listCard('핵심특허·핵심기업 경보', alertRows, 'power');
      c.body.appendChild(lists);
      c.body.appendChild(Insight.box(r, 'overview'));
      c.body.appendChild(Insight.aiPanel('overview', r,
        'Executive Overview — 포트폴리오 전반의 성장/쇠퇴 기술, 신규 조합, 경쟁사 전략변화, 권리장벽·공백영역 요약'));
      c.controls.appendChild(Render.excelButton(null, 'overview_patents'));
    }).catch(function (e) { c.body.innerHTML = Render.statusBlock({ status: 'error', message: e.message }); });
  };

  /* ---------- 헬퍼: 표준 분석 카드 ---------- */
  function analysisCard(opts) {
    // opts: {analysis, title, help, holder, body, renderOk(result, card, chartTargetSetter), controls(card, reload)}
    var c = card(opts.title, opts.help);
    opts.holder.appendChild(c.root);
    if (!availabilityGuard(opts.analysis, c.body)) return null;
    var chartTarget = null;
    c.controls.appendChild(Render.chartButtons(function () { return chartTarget; },
      opts.analysis.replace(/-/g, '_')));
    c.controls.appendChild(Render.excelButton(opts.drill || null, opts.analysis));
    function reload(extraBody) {
      var body = Object.assign({ filters: State.filters }, opts.body || {}, extraBody || {});
      c.body.innerHTML = '<div class="status-empty">불러오는 중…</div>';
      Api.post('/api/' + opts.analysis, body, opts.title + ' 계산 중…').then(function (r) {
        State.lastResults[opts.analysis] = r;
        c.body.innerHTML = '';
        if (r.status !== 'ok') { c.body.innerHTML = Render.statusBlock(r); return; }
        opts.renderOk(r, c, function (t) { chartTarget = t; });
        c.body.appendChild(Insight.box(r, opts.analysis));
        c.body.appendChild(Insight.aiPanel(opts.analysis, r, opts.title + ' — ' + (c.desc || '')));
      }).catch(function (e) {
        c.body.innerHTML = Render.statusBlock({ status: 'error', message: e.message });
      });
    }
    if (opts.controls) opts.controls(c, reload);
    reload();
    return { card: c, reload: reload };
  }

  function plotlyDrill(drill) { Drill.open(drill, '근거 특허'); }

  /* ---------- 버블차트 X/Y축 직접 선택 ----------
     각 포인트의 customdata.m(지표 dict)을 이용해 서버 재계산 없이 축을 재배치한다. */
  var AXIS_FIELDS = {
    'emerging-combinations': {
      fields: { n_ab: '조합 누적 특허 수', growth: '최근 성장률', lift: 'Lift',
                new_applicants: '신규 출원인 수', active_ratio: '유효특허 비율',
                score: 'Emerging Score' } },
    'lifecycle': {
      fields: { maturity: '성숙도(정규화)', momentum: '모멘텀(정규화)', total: '누적 건수',
                growth: '최근 성장률', age: '경과연수', concentration: '출원인 집중도(HHI)',
                new_entrants: '신규 출원인 수', n_applicants: '출원인 수',
                active_ratio: '유효특허 비율', combo_growth: '조합 증가율',
                avg_citations: '평균 피인용' } },
    'opportunity': {
      fields: { attractiveness: '매력도', entry_possibility: '진입 가능성',
                opportunity_score: 'Opportunity Score', barrier: '권리장벽',
                total: '특허 수', growth: '최근 성장률', new_entrants: '신규 출원인 수',
                active_granted: '유효등록 수', cr3: '상위3사 점유율(CR3)' } },
    'portfolio-index': {
      fields: { n: '포트폴리오 규모(건수)', avg_ci: '평균 CI(질)',
                portfolio_index: 'Portfolio Index', avg_tr: '평균 TR(기술 영향력)',
                avg_mc: '평균 MC(시장 커버리지)', growth: '최근 성장률' } }
  };

  function attachAxisPicker(c, holder, analysis) {
    var def = AXIS_FIELDS[analysis];
    if (!def || !holder.data) return;
    function axTitle(ax) {
      if (!ax || !ax.title) return '';
      return typeof ax.title === 'string' ? ax.title : (ax.title.text || '');
    }
    var orig = {
      traces: (holder.data || []).map(function (tr) {
        return { x: (tr.x || []).slice(), y: (tr.y || []).slice() };
      }),
      xTitle: axTitle(holder.layout.xaxis), yTitle: axTitle(holder.layout.yaxis),
      xType: holder.layout.xaxis ? holder.layout.xaxis.type : null,
      xRange: (holder.layout.xaxis && holder.layout.xaxis.range)
        ? holder.layout.xaxis.range.slice() : null,
      yRange: (holder.layout.yaxis && holder.layout.yaxis.range)
        ? holder.layout.yaxis.range.slice() : null,
      shapes: (holder.layout.shapes || []).slice(),
      annotations: (holder.layout.annotations || []).slice()
    };
    var wrap = Ui.el('<span class="axis-picker"><span>축 선택</span></span>');
    function mkSel(axisLabel) {
      var sel = document.createElement('select');
      sel.appendChild(Ui.el('<option value="">' + axisLabel + ': 기본</option>'));
      Object.keys(def.fields).forEach(function (k) {
        var o = document.createElement('option');
        o.value = k; o.textContent = axisLabel + ': ' + def.fields[k];
        sel.appendChild(o);
      });
      return sel;
    }
    var xSel = mkSel('X'), ySel = mkSel('Y');
    function metricArray(tr, key) {
      return (tr.customdata || []).map(function (cd) {
        var v = cd && cd.m ? cd.m[key] : null;
        return (v === undefined || v === null) ? null : v;
      });
    }
    function apply() {
      var xk = xSel.value, yk = ySel.value;
      var custom = !!(xk || yk);
      (holder.data || []).forEach(function (tr, i) {
        if (tr.mode !== 'markers' || !tr.customdata) return;
        var xs = xk ? metricArray(tr, xk) : orig.traces[i].x;
        var ys = yk ? metricArray(tr, yk) : orig.traces[i].y;
        Plotly.restyle(holder, { x: [xs], y: [ys] }, [i]);
      });
      var re = {
        'xaxis.title.text': xk ? def.fields[xk] : orig.xTitle,
        'yaxis.title.text': yk ? def.fields[yk] : orig.yTitle,
        'xaxis.type': xk ? 'linear' : (orig.xType || 'linear'),
        shapes: custom ? [] : orig.shapes,
        annotations: custom ? [] : orig.annotations
      };
      if (custom || !orig.xRange) { re['xaxis.autorange'] = true; }
      else { re['xaxis.range'] = orig.xRange; }
      if (custom || !orig.yRange) { re['yaxis.autorange'] = true; }
      else { re['yaxis.range'] = orig.yRange; }
      Plotly.relayout(holder, re);
    }
    xSel.addEventListener('change', apply);
    ySel.addEventListener('change', apply);
    wrap.appendChild(xSel);
    wrap.appendChild(ySel);
    c.controls.prepend(wrap);
  }

  /* ---------- 1.5 Basic Statistics (WIPS·PatentSight 스타일) ---------- */
  Views.basic = function (content) {
    function statsTab(title, help, keys) {
      return function (h) {
        analysisCard({
          analysis: 'basic-stats', holder: h, title: title, help: help,
          renderOk: function (r, c, setTarget) {
            if (r.kpi && keys.indexOf('annual') >= 0) {
              var k = r.kpi;
              var grid = Ui.el('<div class="kpi-grid" style="margin-bottom:10px"></div>');
              [[Ui.num(k.total, 0), '분석 문헌 수'],
               [k.grant_rate !== null ? Ui.pct(k.grant_rate) : '-', '등록률'],
               [k.active_rate !== null ? Ui.pct(k.active_rate) : '-', '유효율'],
               [k.growth !== null ? Ui.pct(k.growth) : '-', '최근 성장률'],
               [k.peak_year || '-', '최다 출원 연도']].forEach(function (x) {
                grid.appendChild(Ui.el('<div class="kpi"><div class="kpi-value">' +
                  Ui.esc(x[0]) + '</div><div class="kpi-label">' + Ui.esc(x[1]) +
                  '</div></div>'));
              });
              c.body.appendChild(grid);
            }
            var first = true;
            keys.forEach(function (key) {
              var fig = r[key];
              if (!fig) return;
              var holder = Ui.el('<div class="chart-holder"' +
                (key.indexOf('_year') >= 0 ? ' style="min-height:420px"' : '') + '></div>');
              c.body.appendChild(holder);
              Render.plotly(holder, fig, plotlyDrill);
              if (first) { setTarget({ kind: 'plotly', el: holder }); first = false; }
            });
          }
        });
      };
    }
    makeTabs(content, [
      { label: '출원 동향', render: statsTab('연도별 출원 동향 (WIPS형 기본 통계)',
          '연도별 전체 출원·등록·유효 건수 추이입니다. 연도는 출원일(없으면 우선일/공개일) 기준이며, 점을 클릭하면 해당 연도의 근거 특허 목록이 열립니다.',
          ['annual']) },
      { label: '국가·출원인', render: statsTab('국가별 분포 · 출원인 순위 · 활동 매트릭스',
          '국가별 출원 분포, 출원인 순위 Top, 출원인×연도 활동 매트릭스(진할수록 활발)입니다. 막대를 클릭하면 해당 국가/출원인의 특허 목록이 열립니다.',
          ['country', 'applicants', 'applicant_year']) },
      { label: '기술분류 동향', render: statsTab('기술분류별 건수 · 연도 동향',
          '기술분류별 누적 건수 순위와 분류×연도 동향 매트릭스입니다. 다중분류는 Settings 의 처리방식을 따르지 않고 각 분류에 1건씩 계산합니다.',
          ['tech', 'tech_year']) },
      { label: 'Portfolio Index', render: function (h) {
        analysisCard({
          analysis: 'portfolio-index', holder: h,
          title: '포트폴리오 가치 지표 (PatentSight 유사 지표)',
          help: 'TR(기술 영향력)=출원연도 코호트로 보정한 피인용, MC(시장 커버리지)=패밀리 국가 수 표준화, CI=TR×MC, Portfolio Index=유효특허 CI 합계입니다. PatentSight 의 PAI/CI/TR/MC 에서 착안한 유사 지표로 공식 산식과 동일하지 않습니다. 버블: X=규모, Y=평균 CI(질), 크기=Portfolio Index, 색=최근 성장률.',
          renderOk: function (r, c, setTarget) {
            var rank = Ui.el('<div class="chart-holder"></div>');
            c.body.appendChild(rank);
            Render.plotly(rank, r.rank, plotlyDrill);
            setTarget({ kind: 'plotly', el: rank });
            var bub = Ui.el('<div class="chart-holder tall"></div>');
            c.body.appendChild(bub);
            Render.plotly(bub, r.bubble, plotlyDrill);
            attachAxisPicker(c, bub, 'portfolio-index');
            if (r.trend) {
              var tr = Ui.el('<div class="chart-holder" style="min-height:320px"></div>');
              c.body.appendChild(tr);
              Render.plotly(tr, r.trend);
            }
            var rows = (r.top_patents || []).map(function (x) {
              var trEl = document.createElement('tr');
              var td0 = document.createElement('td');
              td0.appendChild(drillCell(x.id, x.drill));
              trEl.appendChild(td0);
              trEl.insertAdjacentHTML('beforeend', '<td>' + Ui.esc(x.title) + '</td><td>' +
                Ui.esc(x.applicant) + '</td><td class="num">' + x.ci + '</td>' +
                '<td class="num">' + x.tr + '</td><td class="num">' + x.mc +
                '</td><td class="num">' + x.cites + '</td>');
              return trEl;
            });
            var tbl = Ui.el(simpleTable(['번호', '명칭', '출원인', 'CI', 'TR', 'MC', '피인용'], []));
            rows.forEach(function (trEl) { tbl.querySelector('tbody').appendChild(trEl); });
            c.body.appendChild(Ui.el('<div style="margin-top:6px"><b style="font-size:12px">' +
              'Competitive Impact 상위 특허</b></div>'));
            c.body.appendChild(tbl);
          }
        });
      } }
    ]);
  };

  /* ---------- 2. Technology Evolution ---------- */
  Views.evolution = function (content) {
    makeTabs(content, [
      { label: '기술 생애주기', render: function (h) {
        analysisCard({
          analysis: 'lifecycle', holder: h, title: '기술 생애주기 Phase Map',
          help: 'X=성숙도(경과연수·누적건수 정규화), Y=모멘텀(성장률·신규출원인 정규화). 단계: Emerging/Growing/Competitive/Mature/Declining/Re-emerging. 화살표=전년 대비 이동.',
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="chart-holder"></div>');
            c.body.appendChild(holder);
            Render.plotly(holder, r.figure, plotlyDrill);
            setTarget({ kind: 'plotly', el: holder });
            attachAxisPicker(c, holder, 'lifecycle');
            var counts = r.phase_counts;
            var badges = Object.keys(counts).filter(function (p) { return counts[p]; })
              .map(function (p) { return '<span class="badge">' + Ui.esc(p) + ' ' + counts[p] + '</span>'; }).join('');
            c.body.appendChild(Ui.el('<div style="margin-top:6px">' + badges + '</div>'));
          }
        });
      } },
      { label: '기술 전이 Sankey', render: function (h) {
        var modeSel;
        analysisCard({
          analysis: 'technology-transition', holder: h, title: '기술분류 전이 Sankey',
          help: '이전 기간→다음 기간 기술 중심 이동. 전이 정의: 패밀리 내 변화/출원인 포트폴리오 변화/후속출원(패밀리 근사)/공동출현 증가.',
          controls: function (c, reload) {
            modeSel = Ui.el('<select><option value="cooccurrence">공동출현 증가</option>' +
              '<option value="applicant">출원인 포트폴리오</option>' +
              '<option value="family">동일 패밀리</option>' +
              '<option value="continuation">후속출원(근사)</option></select>');
            modeSel.addEventListener('change', function () { reload({ mode: modeSel.value }); });
            c.controls.prepend(modeSel);
            var period = Ui.el('<input type="text" size="3" placeholder="기간(년)" title="기간 분할 연 수">');
            period.addEventListener('change', function () {
              reload({ mode: modeSel.value, period_years: Number(period.value) || null });
            });
            c.controls.prepend(period);
          },
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="chart-holder"></div>');
            c.body.appendChild(holder);
            Render.plotly(holder, r.figure, plotlyDrill);
            setTarget({ kind: 'plotly', el: holder });
          }
        });
      } },
      { label: 'Emerging Radar', render: function (h) {
        analysisCard({
          analysis: 'emerging-combinations', holder: h, title: 'Emerging Combination Radar',
          help: 'Score = 가중 기하평균(최근 성장률, Lift, 신규 출원인, 다양성). 정규화: log1p→Winsorize→scaling. 4분면: 좌상 초기 고성장/우상 핵심/우하 성숙·정체/좌하 미성숙.',
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="chart-holder"></div>');
            c.body.appendChild(holder);
            Render.plotly(holder, r.figure, plotlyDrill);
            setTarget({ kind: 'plotly', el: holder });
            attachAxisPicker(c, holder, 'emerging-combinations');
            var rows = (r.combos || []).slice(0, 15).map(function (x) {
              var tr = document.createElement('tr');
              var td0 = document.createElement('td');
              td0.appendChild(drillCell(x.a + ' × ' + x.b, { type: 'combo', a: x.a, b: x.b }));
              tr.appendChild(td0);
              tr.insertAdjacentHTML('beforeend', '<td class="num">' + Ui.num(x.score, 3) + '</td><td class="num">' +
                Ui.num(x.n_ab, 0) + '</td><td class="num">' +
                (x.growth_available ? Ui.pct(x.growth) : '계산 불가') + '</td><td class="num">' +
                Ui.num(x.lift, 2) + '</td><td class="num">' + x.new_applicants + '</td>');
              return tr;
            });
            var tbl = Ui.el(simpleTable(['조합', 'Score', '건수', '성장률', 'Lift', '신규출원인'], []));
            rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
            var wrap = Ui.el('<div style="max-height:280px;overflow:auto;margin-top:8px"></div>');
            wrap.appendChild(tbl);
            c.body.appendChild(wrap);
          }
        });
      } },
      { label: '조합 네트워크', render: function (h) {
        var scope = 'all', company = '';
        analysisCard({
          analysis: 'technology-network', holder: h, title: '기술분류 조합 네트워크',
          help: '노드=기술분류(크기=건수, 테두리=최근 성장률), 엣지=동시분류(두께=Jaccard). 지표: 동시출현·Jaccard·Lift·PMI/NPMI·성장률·신규출원인. 탭: 전체/선택 기업/기업 제외 비교.',
          controls: function (c, reload) {
            var scopeSel = Ui.el('<select><option value="all">전체 시장</option>' +
              '<option value="company">선택 기업</option>' +
              '<option value="market_excl">선택 기업 제외</option></select>');
            var compSel = Ui.el('<select><option value="">기업 선택…</option></select>');
            ((State.filterOptions || {}).applicants || []).slice(0, 60).forEach(function (a) {
              var o = document.createElement('option'); o.value = a; o.textContent = a;
              compSel.appendChild(o);
            });
            var colorSel = Ui.el('<select><option value="l1">색=대분류</option>' +
              '<option value="community">색=커뮤니티</option></select>');
            function go() {
              scope = scopeSel.value; company = compSel.value;
              reload({ scope: scope, company: company || null, color_by: colorSel.value });
            }
            scopeSel.addEventListener('change', go);
            compSel.addEventListener('change', go);
            colorSel.addEventListener('change', go);
            c.controls.prepend(colorSel); c.controls.prepend(compSel); c.controls.prepend(scopeSel);
          },
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="cy-holder"></div>');
            c.body.appendChild(holder);
            var cy = Render.cytoscape(holder, r.network, {
              onEdge: function (d) {
                Drill.open(d.drill, d.source + ' × ' + d.target + ' (Lift ' + d.lift +
                  ', Jaccard ' + d.jaccard + ')');
              }
            });
            setTarget({ kind: 'cy', cy: cy });
            c.body.appendChild(Ui.el('<div style="margin-top:6px;color:#647b8d">노드 ' +
              r.n_nodes + '개 · 엣지 ' + r.n_edges + '개 (상한 적용' +
              (r.meta && r.meta.truncated ? ' · Top-N 절단됨' : '') + ')</div>'));
          }
        });
      } }
    ]);
  };

  /* ---------- 3. Competitor Intelligence ---------- */
  Views.competitor = function (content) {
    makeTabs(content, [
      { label: '기술 DNA', render: function (h) {
        analysisCard({
          analysis: 'company-dna', holder: h, title: '경쟁사 기술 DNA Fingerprint',
          help: '12개 지표(집중도 HHI/다양성 entropy/신규진입률/조합다양성/패밀리규모/해외범위/등록유지율/평균피인용/후속출원/공동출원/발명자집중도/최근성장률). Hover 에 원값·표준화값 동시 표시.',
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="chart-holder"></div>');
            c.body.appendChild(holder);
            Render.plotly(holder, r.figure);
            setTarget({ kind: 'plotly', el: holder });
            c.body.appendChild(Ui.el('<div class="disclaimer">' +
              (r.chart_kind === 'radar'
                ? '레이더 축 값은 비교 대상 기업들 사이에서 상대 평가한 0~1 표준화 점수입니다 ' +
                  '(1 = 비교 기업 중 최고). 지표의 실제 원값은 마우스를 올리면 함께 표시됩니다.'
                : '히트맵 색상은 비교 대상 기업들 사이의 0~1 표준화 점수입니다 (진할수록 높음). ' +
                  '원값은 마우스를 올리면 표시됩니다.') + '</div>'));
            var ph = Ui.el('<div class="chart-holder" style="min-height:300px"></div>');
            c.body.appendChild(ph);
            Render.plotly(ph, r.parcoords);
            c.body.appendChild(Ui.el('<div class="disclaimer">평행좌표: 각 세로축은 지표별 ' +
              '0~1 표준화 점수이며, 하나의 꺾은선이 한 기업입니다.</div>'));
            var rows = (r.companies || []).map(function (x) {
              var tr = document.createElement('tr');
              var td0 = document.createElement('td');
              td0.appendChild(drillCell(x.company, x.drill));
              tr.appendChild(td0);
              tr.insertAdjacentHTML('beforeend', '<td><span class="badge">' + Ui.esc(x.type) + '</span></td>' +
                '<td class="num">' + Ui.num(x.n, 0) + '</td>' +
                '<td class="num">' + (x.raw.recent_growth !== null ? Ui.pct(x.raw.recent_growth) : '-') + '</td>' +
                '<td class="num">' + Ui.num(x.raw.tech_diversity, 2) + '</td>' +
                '<td class="num">' + Ui.num(x.raw.avg_citations, 1) + '</td>');
              return tr;
            });
            var tbl = Ui.el(simpleTable(['기업', '유형(규칙 기반)', '건수', '최근성장', '다양성', '평균피인용'], []));
            rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
            var wrap = Ui.el('<div style="max-height:300px;overflow:auto;margin-top:8px"></div>');
            wrap.appendChild(tbl);
            c.body.appendChild(wrap);
          }
        });
      } },
      { label: '기술 궤적', render: function (h) {
        analysisCard({
          analysis: 'trajectory', holder: h, title: 'Technology Trajectory Map',
          help: '기업·연도별 기술 구성비 벡터를 PCA/UMAP 으로 2D 투영, 연도순 화살표 연결. 가중: 구성비 또는 TF-IDF (출원량 왜곡 방지).',
          controls: function (c, reload) {
            var m = Ui.el('<select><option value="pca">PCA</option><option value="umap">UMAP(불가 시 PCA)</option></select>');
            var w = Ui.el('<select><option value="share">구성비</option><option value="tfidf">TF-IDF</option></select>');
            var go = function () { reload({ method: m.value, weighting: w.value }); };
            m.addEventListener('change', go); w.addEventListener('change', go);
            c.controls.prepend(w); c.controls.prepend(m);
          },
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="chart-holder tall"></div>');
            c.body.appendChild(holder);
            Render.plotly(holder, r.figure, plotlyDrill);
            setTarget({ kind: 'plotly', el: holder });
            c.body.appendChild(Ui.el('<div class="disclaimer">좌표축(주성분 1·2)은 기술 구성비를 ' +
              '2차원으로 압축한 것으로 절대 단위가 없습니다. 점 사이의 거리 = 포트폴리오 구성 차이, ' +
              '화살표 = 연도에 따른 전략 이동 방향으로 해석하세요.</div>'));
            var rows = (r.companies || []).map(function (x) {
              var tr = document.createElement('tr');
              var td0 = document.createElement('td');
              td0.appendChild(drillCell(x.company, x.drill));
              tr.appendChild(td0);
              tr.insertAdjacentHTML('beforeend', '<td class="num">' + Ui.num(x.distance, 2) + '</td><td>' +
                x.years[0] + '–' + x.years[x.years.length - 1] + '</td>');
              return tr;
            });
            var tbl = Ui.el(simpleTable(['기업', '전략 이동거리', '관측 기간'], []));
            rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
            c.body.appendChild(tbl);
          }
        });
      } },
      { label: '선도–추종', render: function (h) {
        analysisCard({
          analysis: 'lead-lag', holder: h, title: '기술 선도–추종 네트워크 (시계열상 선행 신호)',
          help: '기업×기술분류×연도 시계열의 lagged correlation. 화살표=선행→추종, 라벨=평균 시차. 인과관계가 아닌 시계열상 선행 관계입니다.',
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="cy-holder"></div>');
            c.body.appendChild(holder);
            var cy = Render.cytoscape(holder, r.network, {
              onEdge: function (d) {
                Ui.toast(d.source + ' → ' + d.target + ' · 관측 ' + d.n_obs + '회 · 평균 시차 ' +
                  d.avg_lag + '년 · 관련 분류: ' + (d.techs || []).join(', '));
              }
            });
            setTarget({ kind: 'cy', cy: cy });
            var rows = (r.relations || []).map(function (x) {
              return '<td>' + Ui.esc(x.leader) + ' → ' + Ui.esc(x.follower) + '</td>' +
                '<td class="num">' + x.n_obs + '</td><td class="num">' + x.avg_lag +
                '년</td><td class="num">' + x.avg_corr + '</td><td>' +
                (x.techs || []).map(function (t) { return '<span class="badge">' + Ui.esc(t) + '</span>'; }).join('') + '</td>';
            }).map(function (cells) { return cells; });
            c.body.appendChild(Ui.el(simpleTable(['선행→추종', '관측', '평균시차', '평균상관', '기술분류'],
              rows)));
          }
        });
      } },
      { label: '유사도·중첩도', render: function (h) {
        analysisCard({
          analysis: 'company-dna', holder: h, title: '전략 유사도 · 포트폴리오 중첩도',
          help: '전략 유사도=기술 구성비 코사인, 중첩도=활동 분류 집합 Jaccard.',
          renderOk: function (r, c, setTarget) {
            if (r.similarity) {
              var s = Ui.el('<div class="chart-holder"></div>');
              c.body.appendChild(s);
              Render.plotly(s, r.similarity);
              setTarget({ kind: 'plotly', el: s });
              c.body.appendChild(Ui.el('<div class="disclaimer">가로·세로축은 모두 기업이며, ' +
                '셀 값은 두 기업의 기술분류 구성비가 얼마나 비슷한지(코사인 유사도, 0~1)입니다. ' +
                '1에 가까울수록 두 기업의 기술 포트폴리오 구성이 동일합니다.</div>'));
            }
            if (r.overlap) {
              var o = Ui.el('<div class="chart-holder"></div>');
              c.body.appendChild(o);
              Render.plotly(o, r.overlap);
              c.body.appendChild(Ui.el('<div class="disclaimer">중첩도는 두 기업이 활동하는 ' +
                '기술분류 집합이 얼마나 겹치는지(Jaccard, 0~1)입니다. 1 = 완전히 같은 분류에서 활동.</div>'));
            }
          }
        });
      } }
    ]);
  };

  /* ---------- 4. White Space & R&D ---------- */
  Views.whitespace = function (content) {
    makeTabs(content, [
      { label: 'Opportunity Matrix', render: function (h) { renderOpportunity(h); } },
      { label: '문제–해결수단', render: function (h) { renderProblemSolution(h); } },
      { label: '추천 R&D 테마', render: function (h) {
        var c = card('추천 R&D 테마 (Opportunity Score 상위)',
          'Opportunity = 매력도(성장·신규진입·조합·키워드·과제·인접성) × 진입 가능성(1-권리장벽). 자세한 계산은 Opportunity Matrix 탭 참조.');
        h.appendChild(c.root);
        var r = State.lastResults.opportunity;
        function renderIt(res) {
          if (!res || res.status !== 'ok') {
            c.body.innerHTML = '<div class="status-empty">먼저 Opportunity Matrix 탭을 실행하세요.</div>';
            return;
          }
          c.body.innerHTML = '';
          (res.areas || []).slice(0, 10).forEach(function (a, i) {
            var row = Ui.el('<div style="padding:8px;border-bottom:1px solid #eef2f6;display:flex;' +
              'justify-content:space-between;gap:10px;align-items:center"></div>');
            var left = Ui.el('<div></div>');
            left.appendChild(Ui.el('<b>' + (i + 1) + '. </b>'));
            left.appendChild(drillCell(a.tech, { type: 'tech', tech: a.tech }));
            left.appendChild(Ui.el('<span style="color:#647b8d"> — Score ' + Ui.num(a.opportunity_score, 3) +
              (a.own_capability ? ' · <span class="badge good">자사 역량</span>' : '') +
              (a.own_reason ? ' (' + Ui.esc(a.own_reason) + ')' : '') + '</span>'));
            row.appendChild(left);
            row.appendChild(Ui.el('<span class="badge' + (a.barrier > 0.7 ? ' warn' : '') +
              '">장벽 ' + Ui.num(a.barrier, 2) + '</span>'));
            c.body.appendChild(row);
          });
          c.body.appendChild(Insight.box(res, 'opportunity'));
        }
        if (r) renderIt(r);
        else Api.post('/api/opportunity', { filters: State.filters }).then(function (res) {
          State.lastResults.opportunity = res; renderIt(res);
        }).catch(errToast);
      } }
    ]);
  };

  function renderOpportunity(h) {
    var sliderBox = null;
    var res = analysisCard({
      analysis: 'opportunity', holder: h, title: 'Actionable White Space Map',
      help: 'X=매력도(가중 기하평균), Y=진입 가능성(1-권리장벽). 크기=관련 특허 수, 색=권리장벽, ◇=자사 역량 보유. 가중치 슬라이더는 서버 재계산 없이 즉시 반영됩니다.',
      renderOk: function (r, c, setTarget) {
        var holder = Ui.el('<div class="chart-holder tall"></div>');
        c.body.appendChild(holder);
        Render.plotly(holder, r.figure, plotlyDrill);
        setTarget({ kind: 'plotly', el: holder });
        attachAxisPicker(c, holder, 'opportunity');
        // 가중치 슬라이더 (클라이언트 즉시 재계산 — 기본 축 보기에서 동작)
        sliderBox = Ui.el('<div style="margin-top:8px;border-top:1px dashed #e0e8ef;padding-top:8px">' +
          '<b style="font-size:12px">가중치 (즉시 반영 · 축 선택이 기본일 때 적용)</b></div>');
        var labels = { growth: '성장률', new_entrants: '신규 출원인', combo_growth: '조합 증가',
          keyword_growth: '키워드 증가', problem_recurrence: '과제 반복', adjacency: '인접 연결성',
          barrier: '권리장벽(분모)' };
        var weights = Object.assign({}, r.weights);
        function recompute() {
          var areas = r.areas || [];
          var newX = [], newY = [];
          areas.forEach(function (a) {
            var logSum = 0, wSum = 0;
            (r.opportunity_keys || []).forEach(function (k) {
              var w = Math.max(Number(weights[k]) || 0, 0);
              if (w <= 0) return;
              var x = Math.min(Math.max(a.components[k] || 1e-6, 1e-6), 1);
              logSum += w * Math.log(x); wSum += w;
            });
            var attract = wSum > 0 ? Math.exp(logSum / wSum) : 0;
            var entry = 1 - Math.min(a.barrier * Math.max(Number(weights.barrier) || 0.01, 0.01), 1);
            a._x = attract; a._y = entry;
          });
          // trace 별로 좌표 갱신 (자사/일반 두 trace)
          var traceIdx = [];
          holder.data.forEach(function (tr, i) { if (tr.mode === 'markers') traceIdx.push(i); });
          traceIdx.forEach(function (ti) {
            var tr = holder.data[ti];
            var xs = [], ys = [];
            (tr.customdata || []).forEach(function (cd) {
              var a = areas.find(function (x) { return x.tech === (cd && cd.tech); });
              xs.push(a ? a._x : null); ys.push(a ? a._y : null);
            });
            Plotly.restyle(holder, { x: [xs], y: [ys] }, [ti]);
          });
        }
        Object.keys(labels).forEach(function (k) {
          var v = weights[k] !== undefined ? weights[k] : 1;
          var row = Ui.el('<div class="slider-row"><label>' + Ui.esc(labels[k]) + '</label>' +
            '<input type="range" min="0" max="2" step="0.1" value="' + v + '">' +
            '<span class="slider-val">' + v + '</span></div>');
          var input = row.querySelector('input');
          input.addEventListener('input', function () {
            weights[k] = Number(input.value);
            row.querySelector('.slider-val').textContent = input.value;
            recompute();
          });
          sliderBox.appendChild(row);
        });
        var saveBtn = Ui.el('<button class="btn small">가중치 저장 (서버 재계산)</button>');
        saveBtn.addEventListener('click', function () {
          Api.post('/api/settings', { weights: { opportunity: weights } }).then(function () {
            Ui.toast('가중치가 저장되었습니다. 다음 계산부터 서버 점수에 반영됩니다.');
            res && res.reload();
          }).catch(errToast);
        });
        sliderBox.appendChild(saveBtn);
        c.body.appendChild(sliderBox);
      }
    });
  }

  function renderProblemSolution(h) {
    analysisCard({
      analysis: 'problem-solution', holder: h, title: '문제–해결수단 매트릭스',
      help: '행=해결과제, 열=해결수단. 색=최근 성장률, hover=건수·유효비율·상위 출원인. 셀 클릭 시 관련 특허·추이·대표 청구항 패널 표시.',
      renderOk: function (r, c, setTarget) {
        var holder = Ui.el('<div class="chart-holder tall"></div>');
        c.body.appendChild(holder);
        var detail = Ui.el('<div></div>');
        if (r.engine === 'echarts' || r.figure.engine === 'echarts') {
          var chart = Render.echarts(holder, r.figure);
          setTarget({ kind: 'echarts', chart: chart });
          chart.on('click', function (p) {
            var sol = r.solutions[p.data[0]], prob = r.problems[p.data[1]];
            openCell(prob, sol);
          });
        } else {
          Render.plotly(holder, r.figure);
          setTarget({ kind: 'plotly', el: holder });
          holder.on('plotly_click', function (ev) {
            var pt = ev.points && ev.points[0];
            if (!pt) return;
            openCell(pt.y, pt.x);
          });
        }
        c.body.appendChild(detail);
        function openCell(problem, solution) {
          Api.post('/api/problem-solution', {
            filters: State.filters, cell: true, problem: problem, solution: solution
          }, '셀 상세 계산 중…').then(function (d) {
            detail.innerHTML = '';
            if (d.status !== 'ok') { detail.innerHTML = Render.statusBlock(d); return; }
            var panel = card('셀 상세: ' + problem + ' × ' + solution);
            panel.body.innerHTML =
              '<div><span class="badge">특허 ' + Ui.num(d.count, 0) + '건</span>' +
              '<span class="badge">성장률 ' + (d.growth !== null ? Ui.pct(d.growth) : '계산 불가') + '</span>' +
              '<span class="badge">유효비율 ' + (d.active_ratio !== null ? Ui.pct(d.active_ratio) : '미상') + '</span>' +
              '<span class="badge good">Opportunity ' + Ui.num(d.opportunity_score, 3) + '</span></div>' +
              '<div style="margin-top:6px"><b>상위 출원인:</b> ' +
              d.top_applicants.map(function (a) {
                return Ui.esc(a.name) + '(' + a.count + ')';
              }).join(', ') + '</div>' +
              (d.representative_claim
                ? '<div style="margin-top:6px;color:#4b606f"><b>대표 청구항:</b> ' +
                  Ui.esc(d.representative_claim) + '…</div>' : '');
            var trendHolder = Ui.el('<div style="height:200px"></div>');
            panel.body.appendChild(trendHolder);
            Render.plotly(trendHolder, {
              data: [{ type: 'bar', x: d.trend.years, y: d.trend.counts }],
              layout: { margin: { l: 40, r: 10, t: 10, b: 30 }, height: 190 }
            });
            var db = Ui.el('<button class="btn small">근거 특허 보기</button>');
            db.addEventListener('click', function () {
              Drill.open({ type: 'cell', problem: problem, solution: solution },
                problem + ' × ' + solution);
            });
            panel.body.appendChild(db);
            panel.body.appendChild(Insight.box(d, 'problem-solution'));
            detail.appendChild(panel.root);
            panel.root.scrollIntoView({ behavior: 'smooth' });
          }).catch(errToast);
        }
      }
    });
  }

  /* ---------- 5. Patent Power ---------- */
  Views.power = function (content) {
    makeTabs(content, [
      { label: '핵심특허 영향력', render: function (h) {
        analysisCard({
          analysis: 'citation-diffusion', holder: h, title: '핵심특허 영향력 (Influence Score)',
          help: 'Influence = Σ(표준화 지표×가중치): 직접·간접 피인용, 타 분류/타 기업 확산, 패밀리 확장, 유지·권리범위. 가중치는 Settings 에서 조정.',
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="chart-holder"></div>');
            c.body.appendChild(holder);
            Render.plotly(holder, r.figure, plotlyDrill);
            setTarget({ kind: 'plotly', el: holder });
            var rows = (r.top_patents || []).map(function (x) {
              var tr = document.createElement('tr');
              var td0 = document.createElement('td');
              td0.appendChild(drillCell(x.id, x.drill));
              tr.appendChild(td0);
              tr.insertAdjacentHTML('beforeend', '<td>' + Ui.esc(x.title) + '</td><td>' + Ui.esc(x.applicant) +
                '</td><td class="num">' + Ui.num(x.score, 3) + '</td><td class="num">' +
                x.cites + '</td><td>' + (x.expiry ? Ui.esc(x.expiry) : '-') + '</td>');
              return tr;
            });
            var tbl = Ui.el(simpleTable(['번호', '명칭', '출원인', 'Influence', '피인용', '만료예정'], []));
            rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
            c.body.appendChild(tbl);
          }
        });
      } },
      { label: '인용 확산 Sankey', render: function (h) {
        analysisCard({
          analysis: 'citation-diffusion', holder: h, title: 'Citation Diffusion Sankey',
          help: '핵심특허 → 기술분류 → 주요 출원인으로의 영향력 전파 집계 흐름 (인용쌍 데이터가 없어 피인용 수 기반 근사).',
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="chart-holder tall"></div>');
            c.body.appendChild(holder);
            Render.plotly(holder, r.sankey);
            setTarget({ kind: 'plotly', el: holder });
          }
        });
      } },
      { label: '청구항 밀집도', render: function (h) {
        analysisCard({
          analysis: 'claim-density', holder: h, title: '권리장벽 지형도 (Claim Density Contour)',
          help: '독립청구항 임베딩→UMAP/PCA 2D→HDBSCAN 클러스터→KDE 밀도. 점=문헌(크기=피인용, 투명도=권리 유효성, 테두리=등록). FTO 판단이 아닌 우선 검토 스크리닝 도구입니다.',
          controls: function (c, reload) {
            var t = Ui.el('<select><option value="">전체 분류</option></select>');
            ((State.filterOptions || {}).tech || []).slice(0, 50).forEach(function (x) {
              var o = document.createElement('option'); o.value = x; o.textContent = x;
              t.appendChild(o);
            });
            t.addEventListener('change', function () { reload({ tech: t.value || null }); });
            c.controls.prepend(t);
          },
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="chart-holder tall"></div>');
            c.body.appendChild(holder);
            Render.plotly(holder, r.figure, plotlyDrill);
            setTarget({ kind: 'plotly', el: holder });
            var rows = (r.clusters || []).map(function (x) {
              var tr = document.createElement('tr');
              var td0 = document.createElement('td');
              td0.appendChild(drillCell('클러스터 #' + x.cluster, x.drill));
              tr.appendChild(td0);
              tr.insertAdjacentHTML('beforeend', '<td class="num">' + x.n + '</td><td class="num">' + x.density +
                '</td><td class="num">' + (x.active_ratio !== null ? Ui.pct(x.active_ratio) : '미상') +
                '</td><td>' + (x.top_applicants || []).map(function (a) {
                  return Ui.esc(a.name) + '(' + a.count + ')';
                }).join(', ') + '</td>');
              return tr;
            });
            var tbl = Ui.el(simpleTable(['클러스터', '문헌', '중첩밀도', '유효비율', '주요 출원인'], []));
            rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
            c.body.appendChild(tbl);
            c.body.appendChild(Ui.el('<div style="color:#93a5b4;font-size:11px;margin-top:4px">' +
              '방법: ' + Ui.esc(JSON.stringify(r.methods)) + '</div>'));
          }
        });
      } },
      { label: '발명자 이동', render: function (h) {
        analysisCard({
          analysis: 'inventor-mobility', holder: h, title: '발명자 이동 네트워크',
          help: '노드=기업, 엣지=이동 발명자 수(색=대표 기술분류). 동명이인은 공동발명자·분류·시점·국가·희소성 기반 신뢰도로 식별하며 임계값 미만은 "추정 이동"으로 기본 제외.',
          controls: function (c, reload) {
            var chk = Ui.el('<label style="font-size:12px"><input type="checkbox"> 추정 이동 포함</label>');
            chk.querySelector('input').addEventListener('change', function (ev) {
              reload({ include_uncertain: ev.target.checked });
            });
            c.controls.prepend(chk);
          },
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="cy-holder"></div>');
            c.body.appendChild(holder);
            var cy = Render.cytoscape(holder, r.network, {
              onEdge: function (d) {
                var list = (d.inventors || []).map(function (iv) {
                  return iv.name + '(' + iv.year + ', 신뢰도 ' + iv.confidence + ', ' + iv.label + ')';
                }).join(' · ');
                Ui.toast(d.source + ' → ' + d.target + ': ' + list);
              }
            });
            setTarget({ kind: 'cy', cy: cy });
            if (r.years && r.years.length > 1) {
              var slider = Ui.el('<div class="slider-row" style="margin-top:8px">' +
                '<label>연도 필터 (이후)</label>' +
                '<input type="range" min="' + r.years[0] + '" max="' + r.years[r.years.length - 1] +
                '" step="1" value="' + r.years[0] + '"><span class="slider-val">' + r.years[0] + '</span></div>');
              var input = slider.querySelector('input');
              input.addEventListener('input', function () {
                slider.querySelector('.slider-val').textContent = input.value;
                var y = Number(input.value);
                cy.edges().forEach(function (e) {
                  e.style('display', (e.data('year_max') >= y) ? 'element' : 'none');
                });
              });
              c.body.appendChild(slider);
            }
          }
        });
      } }
    ]);
  };

  /* ---------- 6. Data Quality ---------- */
  Views.quality = function (content) {
    makeTabs(content, [
      { label: '분류 품질 진단', render: function (h) {
        analysisCard({
          analysis: 'classification-quality', holder: h, title: '기술분류 품질·경계 진단',
          help: 'Confusion Map: 셀=분류 중심 의미 유사도(임베딩) 또는 중복 특허 비율(폴백). 빨강=경계 모호. 통합/분리/키워드 재정의/다중분류 기준 검토 후보를 자동 제안.',
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="chart-holder tall"></div>');
            c.body.appendChild(holder);
            if (r.confusion.engine === 'echarts') {
              var chart = Render.echarts(holder, r.confusion);
              setTarget({ kind: 'echarts', chart: chart });
            } else {
              Render.plotly(holder, r.confusion);
              setTarget({ kind: 'plotly', el: holder });
              holder.on('plotly_click', function (ev) {
                var pt = ev.points && ev.points[0];
                if (pt && pt.x !== pt.y) {
                  Drill.open({ type: 'combo', a: pt.y, b: pt.x }, pt.y + ' ∩ ' + pt.x);
                }
              });
            }
            var badges = '<span class="badge">다중분류 비율 ' + Ui.pct(r.multi_ratio) + '</span>' +
              (r.silhouette !== null ? '<span class="badge">실루엣 ' + Ui.num(r.silhouette, 3) + '</span>' : '') +
              (r.separation !== null ? '<span class="badge">평균 분리도 ' + Ui.num(r.separation, 3) + '</span>' : '') +
              (r.low_conf_ratio !== null ? '<span class="badge warn">저신뢰 비율 ' + Ui.pct(r.low_conf_ratio) + '</span>' : '');
            c.body.appendChild(Ui.el('<div style="margin-top:6px">' + badges + '</div>'));
            if (r.cohesion_figure) {
              var ch = Ui.el('<div class="chart-holder" style="min-height:280px"></div>');
              c.body.appendChild(ch);
              Render.plotly(ch, r.cohesion_figure);
            }
            if ((r.suggestions || []).length) {
              var rows = r.suggestions.map(function (s) {
                var tr = document.createElement('tr');
                tr.innerHTML = '<td><span class="badge warn">' + Ui.esc(s.type) + '</span></td>';
                var td = document.createElement('td');
                if (s.drill) td.appendChild(drillCell((s.targets || []).join(' ↔ '), s.drill));
                else td.textContent = (s.targets || []).join(' ↔ ');
                tr.appendChild(td);
                tr.insertAdjacentHTML('beforeend', '<td>' + Ui.esc(s.reason) + '</td>');
                return tr;
              });
              var tbl = Ui.el(simpleTable(['제안', '대상 분류', '근거'], []));
              rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
              var wrap = Ui.el('<div style="max-height:260px;overflow:auto;margin-top:8px"></div>');
              wrap.appendChild(tbl);
              c.body.appendChild(wrap);
            }
            if ((r.low_conf_list || []).length) {
              var rows2 = r.low_conf_list.map(function (x) {
                var tr = document.createElement('tr');
                var td0 = document.createElement('td');
                td0.appendChild(drillCell(x.id, { type: 'ids', ids: [x.id] }));
                tr.appendChild(td0);
                tr.insertAdjacentHTML('beforeend', '<td>' + Ui.esc(x.title) + '</td><td class="num">' + x.confidence +
                  '</td><td>' + x.techs.map(function (t) {
                    return '<span class="badge">' + Ui.esc(t) + '</span>';
                  }).join('') + '</td>');
                return tr;
              });
              var tbl2 = Ui.el(simpleTable(['번호', '명칭', '분류 신뢰도', '기술분류'], []));
              rows2.forEach(function (tr) { tbl2.querySelector('tbody').appendChild(tr); });
              var wrap2 = Ui.el('<div style="max-height:220px;overflow:auto;margin-top:8px"></div>');
              wrap2.appendChild(Ui.el('<b style="font-size:12px">저신뢰 분류 특허</b>'));
              wrap2.appendChild(tbl2);
              c.body.appendChild(wrap2);
            }
          }
        });
      } },
      { label: '컬럼 매핑 상태', render: function (h) { renderMappingStatus(h, true); } },
      { label: '출원인 정비 상태', render: function (h) { renderApplicantManager(h, true); } }
    ]);
  };

  function renderMappingStatus(h, readOnly) {
    var c = card('컬럼 매핑 상태 · 분석 가용성 매트릭스',
      '개념 컬럼별 매핑과 분석별 활성/비활성. 매핑 변경은 Settings → 컬럼 매핑에서.');
    h.appendChild(c.root);
    var cfg = State.config;
    if (!cfg || !cfg.availability || !Object.keys(cfg.availability).length) {
      c.body.innerHTML = '<div class="status-empty">Dataset 선택 후 확인할 수 있습니다.</div>';
      return;
    }
    var rows = Object.keys(cfg.availability).map(function (a) {
      var v = cfg.availability[a];
      return '<td>' + Ui.esc(a) + '</td><td class="' +
        (v.available ? 'availability-ok">활성' : 'availability-no">비활성') + '</td><td>' +
        (v.missing || []).map(Ui.esc).join(', ') + '</td><td style="color:#93a5b4">' +
        (v.optional_missing || []).map(Ui.esc).join(', ') + '</td>';
    });
    c.body.innerHTML = simpleTable(['분석', '상태', '누락 필수 컬럼', '누락 선택 컬럼'], rows);
    var mapped = cfg.mapping || {};
    var rows2 = (cfg.concepts || []).map(function (con) {
      var col = mapped[con.key];
      return '<td>' + Ui.esc(con.label) + '</td><td>' + (col ? Ui.esc(col) :
        '<span class="availability-no">미매핑</span>') + '</td><td style="color:#93a5b4">' +
        Ui.esc(con.dtype) + '</td>';
    });
    c.body.innerHTML += '<div style="margin-top:10px"><b>개념 컬럼 매핑</b></div>' +
      simpleTable(['개념 컬럼', '실제 컬럼', '데이터 형식'], rows2);
  }

  function renderApplicantManager(h, readOnly) {
    var c = card('출원인·권리자 표준화 ' + (readOnly ? '상태' : '관리'),
      '자동 표준화(대소문자·법인 접미사·괄호 정리)는 확정값이 아닌 검토·승인 대상입니다. 그룹(자회사→모회사) 및 합병·사명변경 이력 관리, JSON Export/Import 지원.');
    h.appendChild(c.root);
    Api.get('/api/applicant-rules').then(function (data) {
      c.body.innerHTML = '';
      var names = data.names || [];
      if (!names.length) {
        c.body.innerHTML = '<div class="status-empty">Dataset 선택 후 사용 가능합니다.</div>';
        return;
      }
      var pendingMap = {};
      var tbl = Ui.el(simpleTable(['원본명', '건수', '자동 표준명(후보)', '현재 표준명', '상태', ''], []));
      names.slice(0, 200).forEach(function (n) {
        var tr = document.createElement('tr');
        tr.innerHTML = '<td>' + Ui.esc(n.raw) + '</td><td class="num">' + n.count + '</td><td>' +
          Ui.esc(n.auto) + '</td>';
        var tdCur = document.createElement('td');
        var input = Ui.el('<input type="text" style="width:160px" value="' + Ui.esc(n.current) + '"' +
          (readOnly ? ' disabled' : '') + '>');
        tdCur.appendChild(input);
        tr.appendChild(tdCur);
        tr.insertAdjacentHTML('beforeend', '<td>' + (n.approved ? '<span class="badge good">승인됨</span>'
          : '<span class="badge">검토 대기</span>') + '</td>');
        var tdBtn = document.createElement('td');
        if (!readOnly) {
          var ok = Ui.el('<button class="btn small">승인</button>');
          ok.addEventListener('click', function () { pendingMap[n.raw] = input.value; ok.textContent = '대기…'; });
          var rst = Ui.el('<button class="btn small">원복</button>');
          rst.addEventListener('click', function () {
            Api.post('/api/applicant-rules', { reset: [n.raw] }).then(function () {
              Ui.toast('원본값으로 복원되었습니다.'); Views.render(State.view);
            }).catch(errToast);
          });
          tdBtn.appendChild(ok); tdBtn.appendChild(rst);
        }
        tr.appendChild(tdBtn);
        tbl.querySelector('tbody').appendChild(tr);
      });
      var wrap = Ui.el('<div style="max-height:380px;overflow:auto"></div>');
      wrap.appendChild(tbl);
      c.body.appendChild(wrap);
      if (!readOnly) {
        var bar = Ui.el('<div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap"></div>');
        var save = Ui.el('<button class="btn primary small">승인 항목 저장</button>');
        save.addEventListener('click', function () {
          if (!Object.keys(pendingMap).length) { Ui.toast('승인할 항목이 없습니다.', 'warn'); return; }
          Api.post('/api/applicant-rules', { mapping: pendingMap,
            history_entry: '표준명 승인 ' + Object.keys(pendingMap).length + '건' })
            .then(function () { Ui.toast('저장되었습니다.'); Views.render(State.view); })
            .catch(errToast);
        });
        bar.appendChild(save);
        var grpRaw = Ui.el('<input type="text" placeholder="구성사 표준명" style="width:140px">');
        var grpTo = Ui.el('<input type="text" placeholder="그룹 대표명" style="width:140px">');
        var grpBtn = Ui.el('<button class="btn small">그룹 매핑 추가</button>');
        grpBtn.addEventListener('click', function () {
          if (!grpRaw.value || !grpTo.value) return;
          var g = {}; g[grpRaw.value] = grpTo.value;
          Api.post('/api/applicant-rules', { groups: g,
            history_entry: '그룹 설정: ' + grpRaw.value + ' → ' + grpTo.value })
            .then(function () { Ui.toast('그룹이 저장되었습니다.'); }).catch(errToast);
        });
        bar.appendChild(grpRaw); bar.appendChild(grpTo); bar.appendChild(grpBtn);
        var exp = Ui.el('<button class="btn small">규칙 Export(JSON)</button>');
        exp.addEventListener('click', function () {
          var blob = new Blob([JSON.stringify(data.rules || {}, null, 2)], { type: 'application/json' });
          var a = document.createElement('a');
          a.href = URL.createObjectURL(blob); a.download = 'applicant_rules.json'; a.click();
        });
        bar.appendChild(exp);
        var impArea = Ui.el('<textarea class="json-box" placeholder="규칙 JSON 붙여넣기 후 Import"></textarea>');
        var imp = Ui.el('<button class="btn small">Import</button>');
        imp.addEventListener('click', function () {
          try {
            var parsed = JSON.parse(impArea.value);
            Api.post('/api/applicant-rules', { 'import': parsed })
              .then(function () { Ui.toast('가져오기 완료.'); Views.render(State.view); })
              .catch(errToast);
          } catch (e) { Ui.toast('JSON 형식 오류: ' + e.message, 'error'); }
        });
        c.body.appendChild(bar);
        c.body.appendChild(impArea);
        c.body.appendChild(imp);
        var history = (data.rules && data.rules.history) || [];
        if (history.length) {
          c.body.appendChild(Ui.el('<div style="margin-top:8px"><b>변경 이력</b></div>'));
          c.body.appendChild(Ui.el(simpleTable(['시각', '내용'], history.slice(-15).reverse()
            .map(function (hx) {
              return '<td>' + Ui.esc(hx.ts) + '</td><td>' + Ui.esc(hx.entry) + '</td>';
            }))));
        }
      }
    }).catch(errToast);
  }

  /* ---------- 7. Settings ---------- */
  Views.settings = function (content) {
    var grid = Ui.el('<div class="settings-grid"></div>');
    content.appendChild(grid);
    var s = (State.config && State.config.settings) || {};

    /* Dataset & 분석 옵션 */
    var c1 = card('Dataset · 분석 옵션');
    grid.appendChild(c1.root);
    Api.get('/api/datasets').then(function (d) {
      var sel = Ui.el('<select></select>');
      sel.appendChild(Ui.el('<option value="">Dataset 선택…</option>'));
      (d.datasets || []).forEach(function (name) {
        var o = document.createElement('option');
        o.value = name; o.textContent = name;
        if (name === s.dataset) o.selected = true;
        sel.appendChild(o);
      });
      var row = Ui.el('<div class="settings-row"><label>Dataset</label></div>');
      row.appendChild(sel);
      c1.body.prepend(row);
      sel.addEventListener('change', function () {
        saveSettings({ dataset: sel.value || null }, true);
      });
    }).catch(errToast);
    function saveSettings(patch, reloadAll) {
      return Api.post('/api/settings', patch).then(function (resp) {
        State.config.settings = resp.settings;
        Ui.toast('설정이 저장되었습니다.');
        if (reloadAll) boot(true);
      }).catch(errToast);
    }
    function selRow(label, key, options, current, extra) {
      var row = Ui.el('<div class="settings-row"><label>' + Ui.esc(label) + '</label></div>');
      var sel = Ui.el('<select></select>');
      options.forEach(function (o) {
        var opt = document.createElement('option');
        opt.value = o.v !== undefined ? o.v : o; opt.textContent = o.l !== undefined ? o.l : o;
        if (opt.value === String(current)) opt.selected = true;
        sel.appendChild(opt);
      });
      sel.addEventListener('change', function () {
        var patch = {}; patch[key] = sel.value;
        saveSettings(patch, extra && extra.reload);
      });
      row.appendChild(sel);
      return row;
    }
    c1.body.appendChild(selRow('분석 단위', 'analysis_unit',
      [{ v: 'family', l: '패밀리 (기본)' }, { v: 'publication', l: '공개' },
       { v: 'application', l: '출원' }, { v: 'registration', l: '등록' }],
      s.analysis_unit, { reload: true }));
    c1.body.appendChild(selRow('다중분류 처리', 'multiclass_mode',
      [{ v: 'duplicate', l: '중복 계산 (각 분류 1건)' }, { v: 'fractional', l: '1/N 가중' },
       { v: 'primary', l: '대표 분류만' }, { v: 'level_separate', l: '레벨별 집계' }],
      s.multiclass_mode, { reload: true }));
    c1.body.appendChild(selRow('전이 정의 기본값', 'transition_mode',
      [{ v: 'cooccurrence', l: '공동출현 증가' }, { v: 'applicant', l: '출원인 포트폴리오' },
       { v: 'family', l: '동일 패밀리' }, { v: 'continuation', l: '후속출원(근사)' }],
      s.transition_mode));
    c1.body.appendChild(selRow('궤적 가중', 'trajectory_weighting',
      [{ v: 'share', l: '구성비' }, { v: 'tfidf', l: 'TF-IDF' }], s.trajectory_weighting));
    var demoRow = Ui.el('<div class="settings-row"><label>Demo mode</label>' +
      '<label><input type="checkbox" ' + (s.demo_mode ? 'checked' : '') +
      '> 샘플 데이터로 화면 확인 (실제 분석에는 사용 금지)</label></div>');
    demoRow.querySelector('input').addEventListener('change', function (ev) {
      saveSettings({ demo_mode: ev.target.checked }, true);
    });
    c1.body.appendChild(demoRow);
    var ownRow = Ui.el('<div class="settings-row"><label>자사 보유 기술목록</label>' +
      '<input type="text" style="flex:1" placeholder="쉼표로 구분 (White Space 자사 역량 판단)" value="' +
      Ui.esc((s.own_capability_keywords || []).join(', ')) + '"></div>');
    ownRow.querySelector('input').addEventListener('change', function (ev) {
      saveSettings({ own_capability_keywords: ev.target.value.split(',')
        .map(function (x) { return x.trim(); }).filter(Boolean) });
    });
    c1.body.appendChild(ownRow);

    /* LLM & 임베딩 */
    var c2 = card('LLM · 사내 임베딩 연결', 'LLM 은 고정 허용 목록에서만 선택 가능하며 모델 ID/키는 서버에만 저장됩니다.');
    grid.appendChild(c2.root);
    var llmRow = Ui.el('<div class="settings-row"><label>LLM 모델</label></div>');
    var llmSel = Ui.el('<select></select>');
    (State.config.llm_options || []).forEach(function (label) {
      var o = document.createElement('option');
      o.value = label; o.textContent = label;
      if (label === State.config.llm_current) o.selected = true;
      llmSel.appendChild(o);
    });
    llmSel.addEventListener('change', function () { saveSettings({ llm_label: llmSel.value }); });
    llmRow.appendChild(llmSel);
    c2.body.appendChild(llmRow);
    var llmEn = Ui.el('<div class="settings-row"><label>LLM 인사이트</label>' +
      '<label><input type="checkbox" ' + (s.llm_insights_enabled ? 'checked' : '') +
      '> 사용 (실패 시 규칙 기반 자동 폴백, 요약 통계만 전송)</label></div>');
    llmEn.querySelector('input').addEventListener('change', function (ev) {
      saveSettings({ llm_insights_enabled: ev.target.checked });
    });
    c2.body.appendChild(llmEn);
    var emb = s.embedding_adapter || { type: 'none' };
    var embSel = Ui.el('<select><option value="none">사용 안 함 (Dataset 임베딩 컬럼 자동)</option>' +
      '<option value="dataset">사전 계산 벡터 Dataset</option>' +
      '<option value="rest">REST API</option></select>');
    embSel.value = emb.type || 'none';
    var embFields = Ui.el('<div></div>');
    function renderEmbFields() {
      embFields.innerHTML = '';
      if (embSel.value === 'dataset') {
        embFields.innerHTML =
          '<div class="settings-row"><label>Dataset</label><input type="text" id="emb-ds" value="' + Ui.esc(emb.dataset || '') + '"></div>' +
          '<div class="settings-row"><label>ID 컬럼</label><input type="text" id="emb-id" value="' + Ui.esc(emb.id_column || '') + '"></div>' +
          '<div class="settings-row"><label>벡터 컬럼</label><input type="text" id="emb-vec" value="' + Ui.esc(emb.vector_column || '') + '"></div>';
      } else if (embSel.value === 'rest') {
        embFields.innerHTML =
          '<div class="settings-row"><label>Endpoint URL</label><input type="text" id="emb-url" style="flex:1" value="' + Ui.esc(emb.url || '') + '"></div>' +
          '<div class="settings-row"><label>API Key 환경변수명</label><input type="text" id="emb-env" value="' + Ui.esc(emb.api_key_env || '') + '" placeholder="키 자체가 아닌 환경변수 이름"></div>';
      }
    }
    embSel.addEventListener('change', renderEmbFields);
    renderEmbFields();
    var embRow = Ui.el('<div class="settings-row"><label>임베딩 Adapter</label></div>');
    embRow.appendChild(embSel);
    c2.body.appendChild(embRow);
    c2.body.appendChild(embFields);
    var embSave = Ui.el('<button class="btn small">임베딩 설정 저장</button>');
    embSave.addEventListener('click', function () {
      var conf = { type: embSel.value };
      if (embSel.value === 'dataset') {
        conf.dataset = (document.getElementById('emb-ds') || {}).value;
        conf.id_column = (document.getElementById('emb-id') || {}).value;
        conf.vector_column = (document.getElementById('emb-vec') || {}).value;
      } else if (embSel.value === 'rest') {
        conf.url = (document.getElementById('emb-url') || {}).value;
        conf.api_key_env = (document.getElementById('emb-env') || {}).value;
      }
      saveSettings({ embedding_adapter: conf });
    });
    c2.body.appendChild(embSave);

    /* 임계값·상한·가중치 */
    var c3 = card('분석 임계값 · 상한 · 가중치',
      '값 변경 시 캐시가 초기화되고 다음 계산부터 반영됩니다.');
    grid.appendChild(c3.root);
    function numGroup(title, defaults, userVals, settingsKey) {
      var box = Ui.el('<div style="margin-bottom:10px"><b style="font-size:12px">' +
        Ui.esc(title) + '</b></div>');
      var patch = {};
      Object.keys(defaults).forEach(function (k) {
        if (typeof defaults[k] === 'object') return;
        var cur = (userVals && userVals[k] !== undefined) ? userVals[k] : defaults[k];
        var row = Ui.el('<div class="settings-row"><label style="min-width:190px">' + Ui.esc(k) +
          '</label><input type="number" step="any" style="width:110px" value="' + cur + '"></div>');
        row.querySelector('input').addEventListener('change', function (ev) {
          patch[k] = Number(ev.target.value);
        });
        box.appendChild(row);
      });
      var b = Ui.el('<button class="btn small">저장</button>');
      b.addEventListener('click', function () {
        var body = {}; body[settingsKey] = patch;
        saveSettings(body);
      });
      box.appendChild(b);
      return box;
    }
    c3.body.appendChild(numGroup('임계값 (thresholds)', State.config.thresholds_defaults || {},
      s.thresholds, 'thresholds'));
    c3.body.appendChild(numGroup('상한 (limits)', State.config.limits_defaults || {},
      s.limits, 'limits'));
    ['emerging', 'opportunity', 'influence'].forEach(function (g) {
      var defaults = (State.config.weights_defaults || {})[g] || {};
      var user = (s.weights || {})[g] || {};
      var box = Ui.el('<div style="margin-bottom:10px"><b style="font-size:12px">가중치: ' +
        g + '</b></div>');
      var patch = {};
      Object.keys(defaults).forEach(function (k) {
        var cur = user[k] !== undefined ? user[k] : defaults[k];
        var row = Ui.el('<div class="slider-row"><label>' + Ui.esc(k) + '</label>' +
          '<input type="range" min="0" max="2" step="0.1" value="' + cur + '">' +
          '<span class="slider-val">' + cur + '</span></div>');
        var input = row.querySelector('input');
        input.addEventListener('input', function () {
          patch[k] = Number(input.value);
          row.querySelector('.slider-val').textContent = input.value;
        });
        box.appendChild(row);
      });
      var b = Ui.el('<button class="btn small">저장</button>');
      b.addEventListener('click', function () {
        var w = {}; w[g] = patch;
        saveSettings({ weights: w });
      });
      box.appendChild(b);
      c3.body.appendChild(box);
    });

    /* 설정 Export/Import + 실행 로그 */
    var c4 = card('설정 Export/Import · 분석 실행 로그');
    grid.appendChild(c4.root);
    var expBtn = Ui.el('<button class="btn small">사용자 설정 Export (JSON)</button>');
    expBtn.addEventListener('click', function () {
      var blob = new Blob([JSON.stringify(s, null, 2)], { type: 'application/json' });
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = 'ip_landscape_settings.json'; a.click();
    });
    c4.body.appendChild(expBtn);
    var impArea = Ui.el('<textarea class="json-box" placeholder="설정 JSON 붙여넣기"></textarea>');
    var impBtn = Ui.el('<button class="btn small">설정 Import</button>');
    impBtn.addEventListener('click', function () {
      try { saveSettings(JSON.parse(impArea.value), true); }
      catch (e) { Ui.toast('JSON 오류: ' + e.message, 'error'); }
    });
    c4.body.appendChild(impArea);
    c4.body.appendChild(impBtn);
    var logRows = (State.config.run_log || []).map(function (l) {
      return '<td>' + Ui.esc(l.ts) + '</td><td>' + Ui.esc(l.analysis) + '</td><td>' +
        (l.cache_hit ? '캐시' : '계산') + '</td><td class="num">' + l.elapsed_ms +
        'ms</td><td class="num">' + (l.n_rows !== null ? Ui.num(l.n_rows, 0) : '-') +
        '</td><td>' + Ui.esc(l.status) + '</td>';
    });
    var logWrap = Ui.el('<div style="max-height:240px;overflow:auto;margin-top:10px"></div>');
    logWrap.appendChild(Ui.el(simpleTable(['시각', '분석', '캐시', '소요', '행수', '상태'], logRows)));
    c4.body.appendChild(logWrap);

    /* 컬럼 매핑 관리 (전체 폭) */
    var c5 = card('컬럼 매핑 관리', '자동 추천(정규화+사전+유사도) 결과를 검토하고 수동 변경 후 저장하세요. 저장 시 분석 가용성 매트릭스가 갱신됩니다.');
    content.appendChild(c5.root);
    var dsName = s.dataset || (s.demo_mode ? '__demo__' : null);
    if (!dsName) {
      c5.body.innerHTML = '<div class="status-empty">먼저 Dataset 을 선택하세요.</div>';
    } else {
      Api.get('/api/column-mapping?dataset=' + encodeURIComponent(dsName)).then(function (m) {
        c5.body.innerHTML = '';
        var current = Object.assign({}, m.effective);
        function sampleText(col) {
          var vals = (m.samples || {})[col] || [];
          return vals.length ? vals.map(Ui.esc).join(' · ') : '';
        }
        var rows = (m.concepts || []).map(function (con) {
          var tr = document.createElement('tr');
          var sug = m.suggested[con.key];
          var sugHtml = '-';
          if (sug) {
            sugHtml = Ui.esc(sug.column) + ' <span class="badge">' + sug.method + ' ' +
              sug.score + '</span>';
            if (sug.valid === false) {
              sugHtml += ' <span class="badge warn" title="' + Ui.esc(sug.reason || '') +
                '">형식 불일치로 제외</span>';
            }
          }
          tr.innerHTML = '<td>' + Ui.esc(con.label) + '</td><td style="color:#93a5b4">' +
            Ui.esc(con.dtype) + '</td><td>' + sugHtml + '</td>';
          var td = document.createElement('td');
          var sel = document.createElement('select');
          sel.appendChild(Ui.el('<option value="">(매핑 안 함)</option>'));
          (m.columns || []).forEach(function (col) {
            var o = document.createElement('option');
            o.value = col; o.textContent = col;
            if (current[con.key] === col) o.selected = true;
            sel.appendChild(o);
          });
          var tdSample = document.createElement('td');
          tdSample.style.color = '#7a8fa0';
          tdSample.style.fontSize = '11px';
          tdSample.innerHTML = sampleText(current[con.key] || '');
          sel.addEventListener('change', function () {
            if (sel.value) current[con.key] = sel.value;
            else delete current[con.key];
            tdSample.innerHTML = sampleText(sel.value);
          });
          td.appendChild(sel);
          tr.appendChild(td);
          tr.appendChild(tdSample);
          return tr;
        });
        var tbl = Ui.el(simpleTable(['개념 컬럼', '형식', '자동 추천', '매핑', '예시 값(선택 컬럼)'], []));
        rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
        var wrap = Ui.el('<div style="max-height:420px;overflow:auto"></div>');
        wrap.appendChild(tbl);
        c5.body.appendChild(wrap);
        (m.warnings || []).forEach(function (w) { Ui.toast(w, 'warn'); });
        var save = Ui.el('<button class="btn primary" style="margin-top:8px">매핑 저장</button>');
        save.addEventListener('click', function () {
          Api.post('/api/column-mapping', { dataset: dsName, mapping: current })
            .then(function (resp) {
              Ui.toast('매핑이 저장되었습니다.');
              State.config.availability = resp.availability;
              boot(true);
            }).catch(errToast);
        });
        c5.body.appendChild(save);
      }).catch(errToast);
    }

    /* 출원인 표준화 관리 (전체 폭) */
    var holder = Ui.el('<div></div>');
    content.appendChild(holder);
    renderApplicantManager(holder, false);
  };

  /* ---------------------------------------------------------- 프로젝트 */
  function refreshProjects() {
    Api.post('/api/project/load', {}).then(function (d) {
      var sel = document.getElementById('project-list');
      sel.innerHTML = '<option value="">프로젝트…</option>';
      (d.projects || []).forEach(function (p) {
        var o = document.createElement('option');
        o.value = p.name; o.textContent = p.name + ' (' + (p.saved_at || '') + ')';
        sel.appendChild(o);
      });
    }).catch(function () {});
  }
  document.getElementById('btn-save-project').addEventListener('click', function () {
    var name = prompt('프로젝트 이름 (현재 필터·설정 저장):');
    if (!name) return;
    Api.post('/api/project/save', { name: name, filters: Filters.collect() })
      .then(function () { Ui.toast('프로젝트가 저장되었습니다.'); refreshProjects(); })
      .catch(errToast);
  });
  document.getElementById('project-list').addEventListener('change', function (ev) {
    var name = ev.target.value;
    if (!name) return;
    Api.post('/api/project/load', { name: name }).then(function (d) {
      State.config.filter_state = d.project.filters || {};
      Filters.load().then(function () { Views.render(State.view); });
      Ui.toast("프로젝트 '" + name + "' 필터를 불러왔습니다.");
    }).catch(errToast);
  });

  /* ------------------------------------------------------------- 부트 */
  document.getElementById('btn-apply-filters').addEventListener('click', Filters.apply);
  document.getElementById('btn-reset-filters').addEventListener('click', Filters.reset);
  document.querySelectorAll('#ipls-menu li').forEach(function (li) {
    li.addEventListener('click', function () { Views.render(li.getAttribute('data-view')); });
  });

  function boot(keepView) {
    Api.get('/api/config').then(function (cfg) {
      State.config = cfg;
      document.getElementById('ipls-generated-at').textContent = 'v' + cfg.version;
      var hasDataset = cfg.settings.dataset || cfg.settings.demo_mode;
      if (!hasDataset) {
        Ui.toast('Dataset 이 선택되지 않았습니다. Settings 에서 선택하거나 Demo mode 를 켜세요.', 'warn');
        Views.render('settings');
        refreshProjects();
        return;
      }
      Filters.load().then(function () {
        Views.render(keepView ? State.view : 'overview');
        refreshProjects();
      }).catch(function (e) {
        errToast(e);
        Views.render('settings');
      });
    }).catch(function (e) {
      errToast(e);
      document.getElementById('ipls-content').innerHTML =
        '<div class="status-error">Backend 연결에 실패했습니다: ' + Ui.esc(e.message) + '</div>';
    });
  }
  boot(false);
})();

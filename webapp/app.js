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

  /* ---------------------------------------------------- 인증 (앱 수준) */
  var Auth = {
    token: function () {
      try { return localStorage.getItem('ipls_token') || ''; } catch (e) { return ''; }
    },
    user: function () {
      try { return localStorage.getItem('ipls_user') || ''; } catch (e) { return ''; }
    },
    isAdmin: function () {
      try { return localStorage.getItem('ipls_admin') === '1'; } catch (e) { return false; }
    },
    save: function (token, user) {
      try {
        localStorage.setItem('ipls_token', token);
        localStorage.setItem('ipls_user', user.name || '');
        localStorage.setItem('ipls_admin', user.is_admin ? '1' : '0');
      } catch (e) { /* localStorage 미가용 환경 */ }
    },
    clear: function () {
      try {
        localStorage.removeItem('ipls_token');
        localStorage.removeItem('ipls_user');
        localStorage.removeItem('ipls_admin');
      } catch (e) { }
    },
    headers: function (extra) {
      var h = extra || {};
      var t = Auth.token();
      if (t) h['X-IPLS-Auth'] = t;
      return h;
    }
  };

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
      // 라벨은 시작 요청만 설정 — 동시 요청 종료(spin(false))가 진행 중인
      // 요청의 라벨을 기본값으로 되돌리지 않게 한다
      if (on && text) document.getElementById('spinner-text').textContent = text;
      if (pending === 0) document.getElementById('spinner-text').textContent = '계산 중…';
      el.classList.toggle('hidden', pending === 0);
    }
    function handle(resp) {
      return resp.json().catch(function () {
        // 게이트웨이 502/504 등 JSON 이 아닌 응답 — 파서 오류 대신 상태 코드 안내
        throw new Error('서버 응답 오류 (HTTP ' + resp.status + ') — 잠시 후 다시 시도하세요.');
      }).then(function (data) {
        if (data && data.status === 'error') { throw new Error(data.message || '오류'); }
        if (!resp.ok && !(data && data.status)) {
          throw new Error('서버 응답 오류 (HTTP ' + resp.status + ')');
        }
        return data;
      });
    }
    return {
      get: function (path) {
        spin(true);
        return fetch(backendUrl(path), { headers: Auth.headers() }).then(handle)
          .finally(function () { spin(false); });
      },
      post: function (path, body, spinText) {
        spin(true, spinText);
        return fetch(backendUrl(path), {
          method: 'POST',
          headers: Auth.headers({ 'Content-Type': 'application/json' }),
          body: JSON.stringify(body || {})
        }).then(handle).finally(function () { spin(false); });
      },
      upload: function (path, formData, spinText) {
        spin(true, spinText || '업로드 중…');
        return fetch(backendUrl(path), { method: 'POST', body: formData,
                                         headers: Auth.headers() })
          .then(handle).finally(function () { spin(false); });
      },
      download: function (path, body, filename) {
        spin(true, '파일 생성 중…');
        return fetch(backendUrl(path), {
          method: 'POST',
          headers: Auth.headers({ 'Content-Type': 'application/json' }),
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

    function forceYearTicks(fig) {
      /* 연도 축은 항상 1년 = 1칸: 제목에 '연도/year'가 든 수치축에 dtick=1 강제 */
      var lay = fig && fig.layout;
      if (!lay) return;
      Object.keys(lay).forEach(function (k) {
        if (!/^[xy]axis\d*$/.test(k)) return;
        var ax = lay[k];
        if (!ax || ax.type === 'category' || ax.type === 'date') return;
        var t = ax.title ? (ax.title.text || ax.title) : '';
        if (/연도|year/i.test(String(t))) {
          ax.dtick = 1;
          ax.tickformat = 'd';
          if (!ax.tickangle) ax.tickangle = -45;
        }
      });
    }

    function fmtVal(v, blankZero) {
      if (v === null || v === undefined || v === '') return '';
      var n = Number(v);
      if (!isFinite(n)) return '';
      if (blankZero && n === 0) return '';
      if (Math.abs(n) >= 1000) return Math.round(n).toLocaleString();
      if (Number.isInteger(n)) return String(n);
      return n.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
    }

    function addValueLabels(fig) {
      /* 각 그래프에 수치 표시: 막대=값 라벨, 짧은 선그래프=점 위 값, 작은 히트맵=셀 값 */
      (fig.data || []).forEach(function (tr) {
        if (tr.type === 'bar' && !tr.text && !tr.texttemplate) {
          var vals = tr.orientation === 'h' ? tr.x : tr.y;
          if ((vals || []).length && vals.length <= 60) {
            tr.text = vals.map(function (v) { return fmtVal(v); });
            tr.textposition = 'auto';
            tr.textfont = { size: 10 };
            tr.cliponaxis = false;
          }
        } else if ((tr.type === 'scatter' || !tr.type) && /lines/.test(tr.mode || '') &&
                   !/text/.test(tr.mode || '') && !tr.text &&
                   (tr.y || []).length && tr.y.length <= 25 &&
                   tr.y.every(function (v) { return typeof v === 'number'; })) {
          tr.mode = tr.mode + '+text';
          tr.text = tr.y.map(function (v) { return fmtVal(v); });
          tr.textposition = 'top center';
          tr.textfont = { size: 9 };
          tr.cliponaxis = false;
        } else if (tr.type === 'heatmap' && !tr.texttemplate) {
          var cells = (tr.z || []).reduce(function (a, r) { return a + (r ? r.length : 0); }, 0);
          if (cells > 0 && cells <= 400) {
            tr.text = tr.z.map(function (row) {
              return (row || []).map(function (v) { return fmtVal(v, true); });
            });
            tr.texttemplate = '%{text}';
            tr.textfont = { size: 9 };
          }
        }
      });
    }

    function plotly(holder, fig, onDrill) {
      holder.classList.add('ipls-chart');
      forceYearTicks(fig);
      addValueLabels(fig);
      Plotly.newPlot(holder, fig.data, fig.layout, {
        responsive: true, displaylogo: false,
        scrollZoom: false,  // 마우스 휠 스크롤이 차트 확대/축소로 먹히지 않도록
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
      holder.classList.add('ipls-cy');
      holder.__iplsNetwork = network;
      var cy = holder.__iplsCy = cytoscape({
        container: holder,
        elements: network,
        // 페이지 스크롤 중 휠이 네트워크 확대/축소로 먹히는 사고 방지 —
        // 확대는 우상단 PNG 저장 전 브라우저 확대나 드래그 패닝으로 대체
        userZoomingEnabled: false,
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
      holder.classList.add('ipls-echart');
      holder.__iplsOption = option;
      var chart = holder.__iplsChart = echarts.init(holder);
      chart.setOption(option);
      return chart;
    }

    /* 카드 내 렌더링된 차트들의 표시 데이터를 Excel 시트 목록으로 추출 */
    function extractChartSheets(bodyEl, onlyEl) {
      /* onlyEl 지정 시 해당 차트 요소의 시트만 추출 (차트별 인사이트 생성용) */
      var sheets = [];
      function pick(cls) {
        if (onlyEl) return onlyEl.classList.contains(cls) ? [onlyEl] : [];
        return Array.prototype.slice.call(bodyEl.querySelectorAll('.' + cls));
      }
      function axTitle(lt, ax, fb) {
        var a = lt && lt[ax];
        if (!a || !a.title) return fb;
        return (typeof a.title === 'string' ? a.title : a.title.text) || fb;
      }
      function stripHtml(s) { return String(s || '').replace(/<[^>]+>/g, ' ').split('  ')[0].trim(); }
      pick('ipls-chart').forEach(function (gd) {
        if (!gd.data || !gd.layout) return;
        var lt = gd.layout;
        var title = (lt.title && (lt.title.text || lt.title)) || ('chart' + (sheets.length + 1));
        var columns = null, rows = [];
        // 시트 의미 설명(설명 시트용): 차트 제목 + 축·색 의미
        var xTd = stripHtml(axTitle(lt, 'xaxis', ''));
        var yTd = stripHtml(axTitle(lt, 'yaxis', ''));
        var colorTd = '';
        (gd.data || []).forEach(function (tr) {
          var cb = (tr.colorbar && tr.colorbar.title) ||
            (tr.marker && tr.marker.colorbar && tr.marker.colorbar.title);
          if (cb && !colorTd) colorTd = typeof cb === 'string' ? cb : (cb.text || '');
        });
        var descParts = ['차트 제목: ' + String(title)];
        if (xTd) descParts.push('X축: ' + xTd);
        if (yTd) descParts.push('Y축: ' + yTd);
        if (colorTd) descParts.push('색상: ' + colorTd);
        var seriesNames = (gd.data || []).map(function (tr) { return tr.name; })
          .filter(function (n) { return n; });
        if (seriesNames.length > 1) descParts.push('시리즈: ' + seriesNames.join(', '));
        var sheetDesc = descParts.join(' | ');
        (gd.data || []).forEach(function (tr) {
          if (tr.type === 'bar') {
            var h = tr.orientation === 'h';
            var cats = h ? tr.y : tr.x;
            var vals = h ? tr.x : tr.y;
            // 컬럼명에 실제 축 의미 사용 (예: '기술분류', '이전 특허 수')
            var catT = stripHtml(axTitle(lt, h ? 'yaxis' : 'xaxis', '')) || '항목';
            var valT = stripHtml(axTitle(lt, h ? 'xaxis' : 'yaxis', '')) || '값';
            if (!columns) columns = [catT, stripHtml(tr.name || '') || valT];
            else if (tr.name && columns.indexOf(stripHtml(tr.name)) < 0) {
              columns.push(stripHtml(tr.name));
            }
            if (columns.length <= 2) {
              (cats || []).forEach(function (cat, i) { rows.push([cat, vals[i]]); });
            } else {
              // 다중 시리즈 막대: 항목별 행 병합
              (cats || []).forEach(function (cat, i) {
                var found = null;
                for (var ri = 0; ri < rows.length; ri++) {
                  if (rows[ri][0] === cat) { found = rows[ri]; break; }
                }
                if (!found) { found = [cat]; rows.push(found); }
                while (found.length < columns.length - 1) found.push(null);
                found[columns.length - 1] = vals[i];
              });
            }
          } else if (tr.type === 'heatmap' || tr.type === 'contour') {
            if (tr.type === 'contour') return;  // 밀도 그리드는 제외
            // 첫 셀에 행/열 축의 의미를 명시 (예: "해결과제(행) \ 해결수단(열)")
            var yT = stripHtml(axTitle(lt, 'yaxis', '')) || '행';
            var xT = stripHtml(axTitle(lt, 'xaxis', '')) || '열';
            columns = [yT + '(행) \\ ' + xT + '(열)'].concat((tr.x || []).map(String));
            (tr.y || []).forEach(function (yl, ri) {
              rows.push([yl].concat((tr.z && tr.z[ri]) || []));
            });
          } else if (tr.type === 'sankey') {
            columns = ['Source', 'Target', 'Value'];
            var labels = (tr.node && tr.node.label) || [];
            ((tr.link && tr.link.source) || []).forEach(function (s, i) {
              rows.push([labels[s], labels[tr.link.target[i]], tr.link.value[i]]);
            });
          } else if (tr.type === 'treemap') {
            columns = ['분류 경로 (대 > 중 > 소)', '문헌 수', '전체 대비 비율'];
            (tr.ids || []).forEach(function (id, i) {
              var m = tr.customdata && tr.customdata[i] && tr.customdata[i].m;
              rows.push([id, (tr.values || [])[i],
                         m ? m['전체 대비'] : null]);
            });
          } else if (tr.type === 'scatterpolar') {
            if (!columns) columns = ['시리즈'].concat((tr.theta || []).map(String));
            rows.push([tr.name || ''].concat(tr.r || []));
          } else if (tr.type === 'parcoords') {
            columns = (tr.dimensions || []).map(function (d) { return d.label; });
            var nRows = (tr.dimensions && tr.dimensions.length)
              ? tr.dimensions[0].values.length : 0;
            for (var r = 0; r < nRows; r++) {
              rows.push(tr.dimensions.map(function (d) { return d.values[r]; }));
            }
          } else if (tr.type === 'scatter' || !tr.type) {
            var hasM = tr.customdata && tr.customdata.length && tr.customdata[0]
              && tr.customdata[0].m;
            if (hasM) {
              var keys = Object.keys(tr.customdata[0].m);
              columns = ['라벨'].concat(keys);
              tr.customdata.forEach(function (cd, i) {
                var label = (tr.text && tr.text[i])
                  || stripHtml(tr.hovertext && tr.hovertext[i]) || '';
                rows.push([label].concat(keys.map(function (k) {
                  return cd && cd.m ? cd.m[k] : null;
                })));
              });
            } else {
              // m 지표가 없는 산점도: 축 값 + 버블 크기·색상값·hover 설명까지
              // 전달해야 LLM 이 '실제 수치가 없다'며 해석을 포기하지 않는다
              var mk = tr.marker || {};
              var hasSize = Array.isArray(mk.size);
              // 색상값은 수치 배열(컬러바)일 때만 — hex 코드(범주 색)는 LLM 에
              // 해석 불가 노이즈이며 그 의미는 '설명(hover)' 열에 이미 있음
              var hasColor = Array.isArray(mk.color) &&
                typeof mk.color[0] === 'number';
              function hoverTxt(i) {
                var h = tr.hovertext && tr.hovertext[i];
                return h ? String(h).replace(/<br\s*\/?>/gi, '; ')
                  .replace(/<[^>]+>/g, '').slice(0, 160) : null;
              }
              var hasHover = Array.isArray(tr.hovertext);
              columns = ['시리즈', axTitle(lt, 'xaxis', 'X'), axTitle(lt, 'yaxis', 'Y')];
              if (hasSize) columns.push('크기');
              if (hasColor) columns.push(colorTd || '색상값');
              if (hasHover) columns.push('설명');
              (tr.x || []).forEach(function (xv, i) {
                var row = [tr.name || '', xv, (tr.y || [])[i]];
                if (hasSize) row.push(mk.size[i]);
                if (hasColor) row.push(mk.color[i]);
                if (hasHover) row.push(hoverTxt(i));
                rows.push(row);
              });
            }
          }
        });
        if (columns && rows.length) {
          sheets.push({ name: String(title).slice(0, 28), columns: columns, rows: rows,
                        desc: sheetDesc });
        }
        // 렌더러가 부착한 보조 시트 (예: 매트릭스 건수 — 전체 라벨 버전)
        (gd.__iplsExtraSheets || []).forEach(function (s) { sheets.push(s); });
      });
      pick('ipls-cy').forEach(function (el) {
        var net = el.__iplsNetwork;
        if (!net) return;
        var nodeRows = (net.nodes || []).map(function (n) {
          var d = n.data || {};
          return [d.label || d.id, d.count, d.group || '', d.growth];
        });
        if (nodeRows.length) {
          sheets.push({ name: '네트워크 노드', columns: ['노드', '건수', '그룹', '성장률'],
                        rows: nodeRows,
                        desc: '화면 네트워크 그래프의 원(노드) 목록 — 노드·엣지의 의미는 ' +
                          '이 파일의 "카드 설명"과 "차트 해석" 행을 참조하세요.' });
        }
        var edgeRows = (net.edges || []).map(function (e) {
          var d = e.data || {};
          return [d.source, d.target, d.weight, d.jaccard, d.lift, d.avg_lag, d.label || ''];
        });
        if (edgeRows.length) {
          sheets.push({ name: '네트워크 엣지',
                        columns: ['Source', 'Target', '가중치', 'Jaccard', 'Lift', '평균시차', '라벨'],
                        rows: edgeRows,
                        desc: '네트워크의 연결선(엣지) 목록 — Source→Target 방향, ' +
                          '가중치=연결 강도(건수 등). 세부 의미는 "카드 설명" 행 참조.' });
        }
      });
      pick('ipls-echart').forEach(function (el) {
        var opt = el.__iplsOption;
        if (!opt || !opt.series || !opt.series[0]) return;
        var xs = (opt.xAxis && opt.xAxis.data) || [];
        var ys = (opt.yAxis && opt.yAxis.data) || [];
        var rows = (opt.series[0].data || []).map(function (d) {
          return [ys[d[1]], xs[d[0]], d[2]];
        });
        if (rows.length) {
          sheets.push({ name: (opt.title && opt.title.text || '히트맵').slice(0, 28),
                        columns: ['행', '열', '값'], rows: rows,
                        desc: '대형 히트맵의 셀 목록 (행 라벨 / 열 라벨 / 셀 값). ' +
                          '차트 제목: ' + ((opt.title && opt.title.text) || '히트맵') });
        }
      });
      return sheets;
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

    function buildReadmeSheet(bodyEl, sheets) {
      /* 첫 시트 "설명": 이 파일의 데이터가 무엇이고 차트를 어떻게 읽는지 —
         카드 제목·설명, 시트별 축/색 의미, 화면의 차트 해석 캡션·주석을 모두 수록. */
      var rows = [];
      var cardEl = bodyEl && bodyEl.closest ? bodyEl.closest('.card') : null;
      var tEl = cardEl && cardEl.querySelector('.card-title');
      if (tEl) rows.push(['분석 카드', tEl.textContent.trim()]);
      var dEl = cardEl && cardEl.querySelector('.card-desc');
      if (dEl) rows.push(['카드 설명', dEl.textContent.trim()]);
      rows.push(['파일 구성', '시트 1개 = 화면 차트 1개의 집계 데이터입니다. 아래에 각 ' +
        '시트의 축·색 의미와 차트 읽는 법이 정리되어 있습니다. 개별 특허 원본 목록은 ' +
        '화면에서 차트 요소를 클릭(드릴다운)한 뒤 목록의 Excel 버튼으로 받을 수 있습니다.']);
      sheets.forEach(function (s) {
        if (s.desc) rows.push(['시트 「' + s.name + '」', s.desc]);
      });
      if (bodyEl) {
        bodyEl.querySelectorAll('.chart-guide').forEach(function (g) {
          var txt = g.textContent.replace(/[📖💡]/g, '').trim();
          var label = /^이 차트의 인사이트/.test(txt) ? '차트 인사이트' : '차트 해석';
          txt = txt.replace(/^(차트 해석|해석|이 차트의 인사이트)/, '').trim();
          if (txt) rows.push([label, txt]);
        });
        bodyEl.querySelectorAll('.disclaimer').forEach(function (g) {
          var txt = g.textContent.trim();
          if (txt) rows.push(['참고', txt]);
        });
        var insEl = bodyEl.querySelector('.insight-box ul');
        if (insEl && insEl.textContent.trim()) {
          rows.push(['자동 인사이트', Array.prototype.map.call(
            insEl.querySelectorAll('li'),
            function (li) { return '• ' + li.textContent.trim(); }).join('\n')]);
        }
      }
      return { name: '설명', columns: ['항목', '내용'], rows: rows };
    }

    function excelButton(filename, getBody, fallbackDrill) {
      /* 카드에 표시된 차트의 집계 데이터를 Excel(시트당 1개 차트)로 내보낸다.
         첫 시트 "설명"에 데이터·차트 의미를 수록. 차트가 없으면 특허 목록 폴백. */
      var b = Ui.el('<button class="btn small" title="이 카드의 차트 데이터를 Excel 로 다운로드 (설명 시트 포함)">Excel</button>');
      b.addEventListener('click', function () {
        var body = getBody ? getBody() : null;
        var sheets = body ? extractChartSheets(body) : [];
        if (sheets.length) {
          sheets.unshift(buildReadmeSheet(body, sheets));
          Api.download('/api/export-chart',
            { filename: (filename || 'chart') + '_data', sheets: sheets },
            (filename || 'chart') + '_data.xlsx').catch(errToast);
        } else {
          Ui.toast('이 카드에는 차트 데이터가 없어 특허 목록을 내보냅니다.');
          Api.download('/api/export',
            { filters: State.filters, drill: fallbackDrill || null, filename: filename },
            (filename || 'export') + '.xlsx').catch(errToast);
        }
      });
      return b;
    }
    return { statusBlock: statusBlock, plotly: plotly, cytoscape: cytoscape_,
             echarts: echarts_, chartButtons: chartButtons, excelButton: excelButton,
             extractChartSheets: extractChartSheets };
  })();

  /* PPT 저장용: 차트 1개 → PNG data URL 캡처 (Plotly/Cytoscape/ECharts) */
  function captureOneChart(el) {
    try {
      if (el.classList.contains('ipls-chart') && el.data &&
          window.Plotly && Plotly.toImage) {
        return Plotly.toImage(el, { format: 'png', width: 1200, height: 700 })
          .catch(function () { return null; });
      }
      if (el.classList.contains('ipls-cy') && el.__iplsCy && el.__iplsCy.png) {
        return Promise.resolve(el.__iplsCy.png({ full: true, scale: 2,
          output: 'base64uri', bg: '#ffffff' }));
      }
      if (el.classList.contains('ipls-echart') && el.__iplsChart &&
          el.__iplsChart.getDataURL) {
        return Promise.resolve(el.__iplsChart.getDataURL(
          { type: 'png', pixelRatio: 2, backgroundColor: '#fff' }));
      }
    } catch (e) { /* 캡처 실패는 무시 — 텍스트만 저장 */ }
    return Promise.resolve(null);
  }

  /* 카드 안의 차트 요소 목록 (+제목·바로 뒤 해석 캡션) — 차트별 인사이트 생성용 */
  function cardCharts(cardBody) {
    var out = [];
    if (!cardBody) return out;
    cardBody.querySelectorAll('.ipls-chart, .ipls-cy, .ipls-echart')
      .forEach(function (el) {
        var title = '';
        if (el.classList.contains('ipls-chart')) {
          var lt = el.layout || {};
          title = (lt.title && (lt.title.text || lt.title)) || '';
        } else if (el.classList.contains('ipls-echart')) {
          var opt = el.__iplsOption || {};
          title = (opt.title && opt.title.text) || '대형 히트맵';
        } else {
          title = '네트워크 그래프';
        }
        title = String(title).replace(/<[^>]+>/g, ' ').trim();
        // 차트 바로 뒤의 📖 해석 캡션 (있으면 LLM 설명 컨텍스트로 사용)
        var cap = '';
        var holder = el.closest('.chart-holder, .cy-holder, .echart-holder') || el;
        var next = holder.nextElementSibling;
        if (next && next.classList && next.classList.contains('chart-guide')) {
          cap = next.textContent.replace(/[📖💡]/g, '').trim();
        }
        out.push({ el: el, caption: cap,
                   title: title || ('차트 ' + (out.length + 1)) });
      });
    return out;
  }

  /* 카드의 모든 차트 캡처 (최대 6개) */
  function captureCardImages(cardBody, maxN) {
    if (!cardBody) return Promise.resolve([]);
    var charts = cardCharts(cardBody).slice(0, maxN || 6);
    if (!charts.length) return Promise.resolve([]);
    return Promise.all(charts.map(function (ch) { return captureOneChart(ch.el); }))
      .then(function (imgs) {
        return imgs.filter(function (im) { return im; });
      });
  }
  function captureCardImage(cardBody) {
    return captureCardImages(cardBody, 1).then(function (imgs) {
      return imgs[0] || null;
    });
  }

  /* LLM 전달용: 카드에 표시된 차트 데이터를 소형으로 압축 (시트 4 × 행 25 × 열 8).
     onlyEl 지정 시 해당 차트의 데이터만 (차트별 인사이트 생성용). */
  function compactChartData(cardBody, onlyEl) {
    if (!cardBody) return null;
    try {
      var sheets = Render.extractChartSheets(cardBody, onlyEl) || [];
      var out = sheets.slice(0, 4).map(function (s) {
        return {
          name: String(s.name || '').slice(0, 40),
          columns: (s.columns || []).slice(0, 8).map(function (c) {
            return String(c).slice(0, 40);
          }),
          rows: (s.rows || []).slice(0, 25).map(function (r) {
            return (r || []).slice(0, 8).map(function (v) {
              return typeof v === 'number' ? v : String(v === null || v === undefined ? '' : v).slice(0, 40);
            });
          })
        };
      }).filter(function (s) { return s.columns.length && s.rows.length; });
      return out.length ? out : null;
    } catch (e) { return null; }
  }

  /* -------------------------------------------------------------- Insight */
  var Insight = (function () {
    function box(result, analysisName, description) {
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
        var lb = Ui.el('<button class="btn small">LLM 인사이트 생성 (차트별)</button>');
        lb.addEventListener('click', function () {
          var cardEl = div.closest('.card');
          // 차트 의미(카드 설명+해석 가이드)를 함께 전달 → 인사이트에 차트 의미 포함
          var cardDesc = description;
          if (!cardDesc && cardEl) {
            var descEl = cardEl.querySelector('.card-desc');
            cardDesc = (descEl ? descEl.textContent : '').trim();
          }
          var cardBody = cardEl && cardEl.querySelector('.card-body');
          var charts = cardCharts(cardBody).slice(0, 6);
          lb.disabled = true;

          function renderSection(title, data, single) {
            if (!single) {
              var h = document.createElement('li');
              h.textContent = '📊 ' + title;
              h.style.cssText = 'font-weight:700;list-style:none;margin:8px 0 2px -14px';
              ul.appendChild(h);
            }
            (data.sentences || []).forEach(function (s) {
              var li = document.createElement('li');
              li.textContent = s;
              ul.appendChild(li);
            });
            if (data.llm_note) Ui.toast(data.llm_note, 'warn');
          }

          function askOne(ch, idx, single) {
            /* 차트 1개 단위: 해당 차트의 이미지·집계 데이터만 전달해 개별 해석 */
            var desc = ((cardDesc || '') +
              (single ? '' : ' [대상 차트] ' + ch.title) +
              (ch.caption ? ' [차트 읽는 법] ' + ch.caption : '')).trim();
            return captureOneChart(ch.el).then(function (img) {
              return Api.post('/api/insight', {
                analysis: analysisName,
                chart_title: single ? null : ch.title,
                metrics: ins.metrics || {},
                sentences: ins.sentences || [],
                description: desc.slice(0, 900),
                chart_data: compactChartData(cardBody, ch.el),
                chart_image: img,
                chart_images: img ? [img] : []
              }, 'LLM 인사이트 생성 중… (' + (idx + 1) + '/' + charts.length + ')');
            });
          }

          if (!charts.length) {
            // 차트 없는 카드(표 중심): 기존 방식 — 카드 전체 데이터로 1건 생성
            captureCardImages(cardBody).then(function (imgs) {
              return Api.post('/api/insight', {
                analysis: analysisName, metrics: ins.metrics || {},
                sentences: ins.sentences || [],
                description: (cardDesc || '').slice(0, 900),
                chart_data: compactChartData(cardBody),
                chart_image: imgs[0] || null, chart_images: imgs
              }, 'LLM 인사이트 생성 중…');
            }).then(function (data) {
              ul.innerHTML = '';
              renderSection('', data, true);
              src.textContent = '자동 인사이트 (' + (data.source === 'llm' ? 'LLM' : '규칙 기반(폴백)') + ')';
              if (data.saved_id) Ui.toast('🗂️ 인사이트 보관함에 저장되었습니다.');
            }).catch(errToast).finally(function () { lb.disabled = false; });
            return;
          }

          // 카드의 각 차트에 대해 순차적으로 개별 인사이트 생성·저장
          var single = charts.length === 1;
          ul.innerHTML = '';
          var saved = 0;
          var chain = Promise.resolve();
          charts.forEach(function (ch, idx) {
            chain = chain.then(function () {
              return askOne(ch, idx, single).then(function (data) {
                renderSection(ch.title, data, single);
                if (data.saved_id) saved += 1;
              });
            });
          });
          chain.then(function () {
            src.textContent = '자동 인사이트 (LLM · 차트별 ' + charts.length + '건)';
            if (saved) {
              Ui.toast('🗂️ 차트별 인사이트 ' + saved + '건이 보관함에 저장되었습니다 ' +
                '(PPT 다운로드 시 각 차트+인사이트가 모두 포함).');
            }
          }).catch(errToast).finally(function () { lb.disabled = false; });
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
      var webSearchOn = !!(State.config && State.config.settings &&
        State.config.settings.web_search_enabled);
      var panel = Ui.el(
        '<div class="ai-panel">' +
        '<div class="ai-head"><span class="ai-title">🤖 AI 인사이트</span>' +
        (webSearchOn ? '<label class="ai-web" title="답변에 외부 웹 검색 결과를 참고 자료로 ' +
          '첨부합니다 (실패 시 내부 데이터만 사용)">' +
          '<input type="checkbox" checked> 웹 검색 포함</label>' : '') +
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
      var webChk = panel.querySelector('.ai-web input');

      function addMsg(role, text, source, webSources) {
        var m = Ui.el('<div class="chat-msg ' + role + '"></div>');
        m.textContent = text;
        if (role === 'assistant') {
          m.appendChild(Ui.el('<span class="chat-src">' +
            (source === 'llm' ? 'LLM 생성 (요약 통계 기반)' : '규칙 기반 폴백') + '</span>'));
          if (webSources && webSources.length) {
            var srcBox = Ui.el('<div class="chat-websrc"><b>🔗 웹 출처</b></div>');
            webSources.forEach(function (s, i) {
              var a = Ui.el('<a target="_blank" rel="noopener noreferrer"></a>');
              a.href = String(s.url || '#');
              a.textContent = '(' + (i + 1) + ') ' + (s.title || s.url || '');
              srcBox.appendChild(a);
            });
            m.appendChild(srcBox);
          }
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
        var cardEl = panel.closest('.card');
        var cardBody = cardEl && cardEl.querySelector('.card-body');
        captureCardImages(cardBody).then(function (imgs) {
          return Api.post('/api/insight', {
            analysis: analysisName, chat: true, question: question || null,
            history: history.slice(-8),
            metrics: ins.metrics || {}, sentences: ins.sentences || [],
            description: (description || '').slice(0, 500),
            chart_data: compactChartData(cardBody),
            chart_image: imgs[0] || null,
            chart_images: imgs,
            web_search: !!(webChk && webChk.checked)
          }, 'AI 인사이트 생성 중…');
        }).then(function (d) {
          addMsg('assistant', d.answer || '(응답 없음)', d.source, d.web_sources);
          if (d.web_note) {
            log.appendChild(Ui.el('<div class="chat-src" style="padding:2px 6px">' +
              Ui.esc(d.web_note) + '</div>'));
          }
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

  function chartCap(text) {
    /* 개별 차트 바로 아래에 붙는 축 의미·해석 캡션 */
    return Ui.el('<div class="chart-guide"><b>📖 해석</b>' + Ui.esc(text) + '</div>');
  }

  function miniInsight(sentences) {
    /* 개별 차트 바로 아래에 붙는 차트별 인사이트 (전체 인사이트와 분리) */
    var div = Ui.el('<div class="chart-guide" style="border-left:3px solid #59A14F">' +
      '<b>💡 이 차트의 인사이트</b></div>');
    var ul = document.createElement('ul');
    ul.style.cssText = 'padding-left:16px;margin:4px 0 0';
    (sentences || []).forEach(function (s) {
      var li = document.createElement('li');
      li.textContent = s;
      ul.appendChild(li);
    });
    div.appendChild(ul);
    return div;
  }

  function definitionsTable(definitions, officialDiff) {
    /* 지표 정의표: 지표 | 정의 | 계산식 | 해석 (+공식 지수와의 차이 목록) */
    var wrap = Ui.el('<div style="margin-bottom:12px"></div>');
    if (!definitions || !definitions.length) return wrap;
    wrap.appendChild(Ui.el('<div style="font-weight:700;font-size:12.5px;margin-bottom:4px">' +
      '📐 지표 정의</div>'));
    var rows = definitions.map(function (d) {
      return '<td style="white-space:nowrap"><b>' + Ui.esc(d.code) + '</b><br>' +
        '<span style="color:#647b8d;font-size:11px">' + Ui.esc(d.name) + '</span></td>' +
        '<td>' + Ui.esc(d.definition) + '</td>' +
        '<td><code style="font-size:11px">' + Ui.esc(d.formula) + '</code><br>' +
        '<span style="color:#93a5b4;font-size:10.5px">' + Ui.esc(d.basis || '') + '</span></td>' +
        '<td>' + Ui.esc(d.reading) + '</td>';
    });
    var tblWrap = Ui.el('<div style="overflow-x:auto"></div>');
    tblWrap.appendChild(Ui.el(simpleTable(['지표', '정의', '계산식', '해석'], rows)));
    wrap.appendChild(tblWrap);
    if (officialDiff && officialDiff.length) {
      var diffBox = Ui.el('<details style="margin:8px 0"><summary style="cursor:pointer;' +
        'font-size:12.5px;font-weight:700;color:#46607a">📌 공식 지수(PatentSight)와 ' +
        '본 계산의 차이 — 펼쳐 보기</summary></details>');
      var ul = document.createElement('ul');
      ul.style.cssText = 'padding-left:18px;font-size:12px;line-height:1.7;color:#4b606f;margin:6px 0';
      officialDiff.forEach(function (s) {
        var li = document.createElement('li');
        li.textContent = s;
        ul.appendChild(li);
      });
      diffBox.appendChild(ul);
      wrap.appendChild(diffBox);
    }
    return wrap;
  }

  /* ---------------------------------------------------------------- Views */
  var Views = {};

  // 컨테이너 비우기 전 차트 엔진 인스턴스 해제 — 장시간 탭 이동 시
  // WebGL 컨텍스트·리스너 누수 방지 (해제 실패는 무시해도 무해)
  function disposeCharts(container) {
    if (!container || !container.querySelectorAll) return;
    container.querySelectorAll('.ipls-chart, .ipls-cy, .ipls-echart')
      .forEach(function (el) {
        try {
          if (el.classList.contains('ipls-chart') && window.Plotly && Plotly.purge) {
            Plotly.purge(el);
          } else if (el.__iplsCy && el.__iplsCy.destroy) {
            el.__iplsCy.destroy();
          } else if (el.__iplsChart && el.__iplsChart.dispose) {
            el.__iplsChart.dispose();
          }
        } catch (e) { /* 해제 실패는 렌더에 영향 없음 */ }
      });
  }

  Views.render = function (view) {
    State.view = view;
    document.querySelectorAll('#ipls-menu li').forEach(function (li) {
      li.classList.toggle('active', li.getAttribute('data-view') === view);
    });
    var content = document.getElementById('ipls-content');
    disposeCharts(content);
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
        disposeCharts(holder);
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

  /* ---------- 0. 목적 맞춤 분석 (분석 목적 → 추천 차트 우선 표시) ---------- */
  // 각 항목: v=메뉴(view), t=탭 라벨(정확히 일치해야 딥링크 동작), why=이 목적에
  // 왜 맞는지 한 줄. primary 배열=핵심 차트(순서=우선순위), secondary=보조 차트.
  var PURPOSES = [
    { key: 'tech_trend', icon: '📈', label: '기술 동향 분석',
      desc: '어떤 기술이 성장·쇠퇴하는지', users: '연구소, CTO',
      primary: [
        { v: 'evolution', t: '기술 생애주기', why: '기술별 성숙도×모멘텀으로 성장/성숙/쇠퇴/재부상 단계를 한 화면에서 판정' },
        { v: 'evolution', t: '기술분류 동향', why: '분류별 연도 추이 — 어떤 기술의 출원이 늘고 줄었는지 기본 확인' },
        { v: 'evolution', t: '기술×연도 버블', why: '대·중·소 분류별 투자 시점·규모를 셀 단위로 비교 (회사 비교 가능)' },
        { v: 'evolution', t: '기술 전이 Sankey', why: '기술 간 이동 흐름 — 어디에서 어디로 무게중심이 옮겨가는지' },
        { v: 'evolution', t: '신흥 기술 탐지 (임베딩)', why: '분류 체계에 아직 안 잡힌 신흥 주제를 텍스트 군집으로 조기 포착' }],
      secondary: [
        { v: 'evolution', t: 'Emerging Radar', why: '성장률×Lift 기준 뜨는 기술 조합' },
        { v: 'evolution', t: '조합 네트워크', why: '기술 간 연결 구조 — 융합이 일어나는 축 확인' },
        { v: 'power', t: '인용 확산 Sankey', why: '어느 기술이 후속 기술을 낳는지 — 파급의 방향' },
        { v: 'evolution', t: '기술분류 트리', why: '대›중›소 구성비 전체 조망' },
        { v: 'basic', t: '출원 동향', why: '전체 출원량의 큰 흐름 확인' }] },
    { key: 'competitor', icon: '🏢', label: '경쟁사 분석',
      desc: '경쟁사가 무엇을 개발하는지', users: '전략기획, IP팀',
      primary: [
        { v: 'competitor', t: '출원인 포커스', why: '경쟁사의 집중 기술(주력) + 🆕 신규 진입 기술(최근 N년 첫 출원) + ★ 급부상 아이템을 한 화면에서' },
        { v: 'evolution', t: '기술×연도 버블', why: '경쟁사 선택 — 어떤 기술에 언제 진입해 얼마나 투자했는지 시점·규모 비교 (최대 3사)' },
        { v: 'overview', t: '경영 요약', why: '경쟁 포지션 맵·BCG — 성장률×질 기준 경쟁사 위치 비교' },
        { v: 'overview', t: '🚨 위협 레이더', why: '자사 주력 기술에 새로 진입한 경쟁자 조기 경보' },
        { v: 'competitor', t: '기술 DNA', why: '경쟁사별 12지표 프로파일 — 어떤 유형의 플레이어인지' },
        { v: 'competitor', t: '유사도·중첩도', why: '자사와 포트폴리오가 겹치는 회사 순위 — 직접 경쟁 상대 식별' }],
      secondary: [
        { v: 'competitor', t: '기술 궤적', why: '경쟁사의 연도별 기술 이동 경로' },
        { v: 'evolution', t: '신흥 기술 탐지 (임베딩)', why: '경쟁사 선택 — 분류에 아직 안 잡힌 그 회사의 새 주제(신규 진입) 조기 포착' },
        { v: 'power', t: '발명자 이동', why: '경쟁사 간 인력 이동 — 기술 유출입 신호' },
        { v: 'deepsig', t: '시그널: 심사 이력', why: '경쟁사 선택 — 우선심사 급등 기술 = 사업화 임박 신호' },
        { v: 'basic', t: '국가·출원인', why: '출원인 순위·활동 매트릭스 기본 비교' },
        { v: 'competitor', t: 'Patent Asset Index', why: '경쟁사 포트폴리오 가치 정량 비교' }] },
    { key: 'rnd_direction', icon: '🧭', label: 'R&D 방향 수립',
      desc: '앞으로 개발할 분야 선정', users: '연구소',
      primary: [
        { v: 'whitespace', t: '추천 R&D 테마', why: '기회 점수 기반 추천 테마 — 방향 후보를 바로 제시' },
        { v: 'whitespace', t: 'Opportunity Matrix', why: '매력도×진입장벽으로 "지금 들어갈 만한" 영역 선별' },
        { v: 'evolution', t: '신흥 기술 탐지 (임베딩)', why: '최근에 몰리는 신흥 주제 — 선점 후보' },
        { v: 'evolution', t: '기술 생애주기', why: '도입기/성장기 기술 = 투자 적기 판단' }],
      secondary: [
        { v: 'evolution', t: 'Emerging Radar', why: '뜨는 기술 조합에서 융합 테마 발굴' },
        { v: 'evolution', t: '기술 전이 Sankey', why: '기존 기술이 어디로 이동 중인지 — 다음 단계 예측 재료' },
        { v: 'competitor', t: '선도–추종', why: '선행 지표 기업의 방향 = 미래 힌트' },
        { v: 'whitespace', t: '문제–해결수단', why: '과제×수단 매트릭스의 빈 칸 = 미해결 문제' },
        { v: 'overview', t: '💰 R&D 효율', why: '자원 배분 전 현재 효율 진단' },
        { v: 'overview', t: '⏱️ 추격 시계', why: '따라잡기 가능한 분야 vs 불가능한 분야 구분' }] },
    { key: 'white_space', icon: '🎯', label: 'White Space 발굴',
      desc: '아직 특허가 없는 영역 찾기', users: '연구개발',
      primary: [
        { v: 'whitespace', t: 'Opportunity Matrix', why: '시장 매력도 대비 특허 장벽이 낮은 공백 영역 지도' },
        { v: 'whitespace', t: '미점유 조합 (UpSet)', why: '기술 조합 중 아직 아무도 출원하지 않은 조합 목록' },
        { v: 'whitespace', t: '문제–해결수단', why: '풀리지 않은 문제(빈 셀)와 대체 수단 후보' }],
      secondary: [
        { v: 'evolution', t: '분류축 교차 (A·B·C)', why: '분류축 교차의 희소 셀 = 공백 후보' },
        { v: 'evolution', t: '조합 네트워크', why: '연결이 약한 기술 쌍 = 미개척 융합' },
        { v: 'evolution', t: '신흥 기술 탐지 (임베딩)', why: '공백이 채워지기 시작하는 신호 감시' },
        { v: 'evolution', t: '기술분류 트리', why: '분류 구조에서 유난히 작은 가지 = 미발달 영역 후보' },
        { v: 'whitespace', t: '추천 R&D 테마', why: '공백 기반 추천 테마로 연결' }] },
    { key: 'design_around', icon: '🛠️', label: '특허 회피 (Design Around)',
      desc: '침해를 피할 기술 찾기', users: '개발팀',
      note: '⚠️ 이 화면들은 회피 검토의 출발점(통계 신호)입니다 — 실제 침해 판단·회피 설계는 청구항 해석이 필요하며 반드시 전문 대리인 검토를 거치세요.',
      primary: [
        { v: 'power', t: '핵심특허 영향력', why: '피해가야 할 장벽 특허(높은 영향력)를 먼저 특정' },
        { v: 'power', t: '권리 중첩 네트워크 (임베딩)', why: '자사 아이디어와 의미상 겹치는 특허 군집 확인' },
        { v: 'power', t: '청구항 밀집도', why: '청구항이 촘촘한 영역(회피 어려움) vs 성긴 영역(여지 있음)' },
        { v: 'whitespace', t: '문제–해결수단', why: '같은 문제의 다른 해결수단 = 회피 설계 후보' }],
      secondary: [
        { v: 'competitor', t: '권리범위 엔트로피', why: '권리범위가 넓은 출원인/특허 파악' },
        { v: 'deepsig', t: '시그널: 수명·시장', why: '연차료 미납 소멸 특허 = 자유 사용 후보 (등록원부 확인 필수)' },
        { v: 'deepsig', t: '시그널: 심사 이력', why: '심사관 인용이 유난히 많은 기술 = 회피 대신 무효 검토가 유효할 수 있는 영역' },
        { v: 'basic', t: '심화 분석', why: '만료 타임라인 — 곧 풀리는 특허 확인' },
        { v: 'power', t: '인용 확산 Sankey', why: '장벽 특허의 후속 인용 흐름 파악' }] },
    { key: 'fto', icon: '⚖️', label: 'FTO (자유실시조사)',
      desc: '제품 출시 가능 여부', users: '특허팀',
      note: '⚠️ 본 앱은 FTO 의 사전 스크리닝(통계 신호)만 제공합니다. 자유실시 여부는 국가별 유효 청구항 해석이 필요한 법률 판단으로, 반드시 변리사·변호사의 정식 FTO 의견으로 확인하세요.',
      primary: [
        { v: 'power', t: '핵심특허 영향력', why: '출시 예정 기술 영역의 강한 특허(피인용·패밀리)를 우선 식별' },
        { v: 'overview', t: '📅 만료 절벽', why: '핵심 장벽 특허의 만료 시점 = 출시 타이밍 검토 재료' },
        { v: 'deepsig', t: '시그널: 수명·시장', why: '법적 상태·연차료 생존 — 이미 소멸한 특허 구분 (원부 확인 필수)' },
        { v: 'deepsig', t: '시그널: 분쟁·국가과제', why: '심판·소송이 몰린 기술 = 분쟁 리스크 높은 영역' }],
      secondary: [
        { v: 'deepsig', t: '시그널: 라이선스·표준·양도', why: 'SEP(표준특허) 선언 여부 — 회피 불가 특허 확인' },
        { v: 'power', t: '권리 중첩 네트워크 (임베딩)', why: '자사 제품 기술과 의미상 근접한 타사 특허 스크리닝' },
        { v: 'basic', t: '국가·출원인', why: '출시 대상 국가에 권리를 보유한 주체 분포 확인' },
        { v: 'basic', t: '심화 분석', why: '만료 타임라인으로 잔존 권리 기간 확인' }] },
    { key: 'portfolio', icon: '📂', label: '특허 포트폴리오 평가',
      desc: '우리 특허의 강약점 분석', users: 'IP팀',
      primary: [
        { v: 'competitor', t: 'Patent Asset Index', why: '공식 방법론(TR×MC=CI)으로 자사 포트폴리오 가치를 경쟁사와 정량 비교' },
        { v: 'competitor', t: 'Portfolio 종합', why: '규모·질·성장 종합 지표 한 화면' },
        { v: 'overview', t: '💰 R&D 효율', why: '출원 규모 대비 질 — 자사가 어느 사분면인지' },
        { v: 'overview', t: '✂️ 포트폴리오 다이어트', why: '유지비 재검토 후보 선별 — 약점 정리' },
        { v: 'competitor', t: '기술 DNA', why: '자사 선택 시 12지표 강약점 프로파일' }],
      secondary: [
        { v: 'power', t: '핵심특허 영향력', why: '자사 선택 — 보유 핵심특허의 영향력 확인' },
        { v: 'competitor', t: '권리범위 엔트로피', why: '권리범위 다양성 — 집중형인지 분산형인지' },
        { v: 'overview', t: '👤 키맨 리스크', why: '핵심 발명자 의존도 = 조직 리스크' },
        { v: 'power', t: '청구항 밀집도', why: '청구항 구조의 촘촘함 — 권리 강도 보조 지표' },
        { v: 'competitor', t: '출원인 포커스', why: '자사 선택 — 집중 기술과 신규 진입·급부상까지 자사 포트폴리오의 움직임 확인' },
        { v: 'overview', t: '📅 만료 절벽', why: '자사 핵심특허 만료 시점 = 방어 공백 리스크' },
        { v: 'quality', t: '검증 리포트', why: '평가 근거 데이터의 정합성 먼저 확인' }] },
    { key: 'ma_investment', icon: '💼', label: 'M&A/투자 검토',
      desc: '기업 기술력 평가', users: '투자부서',
      primary: [
        { v: 'competitor', t: 'Patent Asset Index', why: '대상 기업 포트폴리오 가치의 정량 평가 (공개 방법론)' },
        { v: 'power', t: '핵심특허 영향력', why: '대상 기업 선택 — 진짜 가치 있는 핵심 자산 식별' },
        { v: 'competitor', t: '기술 DNA', why: '대상 기업의 기술 체질 — 선점형인지 추격형인지' },
        { v: 'power', t: '발명자 이동', why: '핵심 인력이 남아 있는가 — 이탈했다면 자산 가치 할인' }],
      secondary: [
        { v: 'overview', t: '👤 키맨 리스크', why: '소수 발명자 의존도 = 인수 후 리스크' },
        { v: 'competitor', t: '출원인·권리자 관계', why: '이미 양도된 권리·담보 설정 여부 확인' },
        { v: 'deepsig', t: '시그널: 분쟁·국가과제', why: '진행 중 분쟁 = 우발 부채 후보' },
        { v: 'deepsig', t: '시그널: 라이선스·표준·양도', why: '실시권 수익·SEP 보유 = 가치 가산 요소' },
        { v: 'competitor', t: 'Portfolio 종합', why: '규모·질·성장 종합 — 대상 기업의 전체 체력' },
        { v: 'deepsig', t: '시그널: 수명·시장', why: '연차료 유지 행태 = 스스로 매긴 특허 가치·관리 품질' },
        { v: 'competitor', t: '기술 궤적', why: '기술 방향의 일관성 — 전략 실행력 방증' }] },
    { key: 'national_rnd', icon: '🏛️', label: '국가 R&D 기획',
      desc: '국가 연구과제 선정', users: '정부기관',
      primary: [
        { v: 'evolution', t: '신흥 기술 탐지 (임베딩)', why: '민간이 이미 달리는 신흥 주제 vs 공백 주제 구분' },
        { v: 'evolution', t: '기술 생애주기', why: '도입기 기술 = 정부 마중물 효과가 큰 후보' },
        { v: 'whitespace', t: 'Opportunity Matrix', why: '민간 투자가 닿지 않은 공백 = 공공 투자 후보' },
        { v: 'deepsig', t: '시그널: 거절·과학·심사관', why: '과학(논문) 연계성 — 기초연구에 가까운 기술 식별' }],
      secondary: [
        { v: 'deepsig', t: '시그널: 분쟁·국가과제', why: '기존 국가과제가 만든 특허 지형 — 중복 투자 방지' },
        { v: 'basic', t: '국가·출원인', why: '국가별 분포 — 해외 대비 국내 위치 확인' },
        { v: 'whitespace', t: '미점유 조합 (UpSet)', why: '아무도 안 하는 조합 — 선도 투자 후보' },
        { v: 'evolution', t: 'Emerging Radar', why: '융합 조합의 성장 신호 — 학제간 과제 발굴' },
        { v: 'competitor', t: '선도–추종', why: '해외 선행 → 국내 추종 시차 = 추격 전략 재료' }] },
    { key: 'license', icon: '🤝', label: '라이선스 전략',
      desc: '기술 이전 대상 발굴', users: '사업부',
      primary: [
        { v: 'deepsig', t: '시그널: 라이선스·표준·양도', why: '실제 실시권·양도 거래 기록 — 시장이 형성된 기술 확인' },
        { v: 'power', t: '핵심특허 영향력', why: '라이선스 가치가 높은 자사 핵심특허 선별' },
        { v: 'power', t: '인용 확산 Sankey', why: '자사 특허를 인용하는 회사 = 잠재 수요자 후보' }],
      secondary: [
        { v: 'competitor', t: '유사도·중첩도', why: '자사 기술과 겹치는 회사 = 이전·제휴 대상 후보' },
        { v: 'competitor', t: '출원인·권리자 관계', why: '양도 네트워크에서 활발한 매수자 식별' },
        { v: 'deepsig', t: '시그널: 수명·시장', why: '지정국 진입 패턴 — 어느 시장에서 권리가 필요한지' },
        { v: 'power', t: '의미 기반 영향력 (임베딩)', why: '인용이 없어도 의미상 후속인 특허 = 숨은 수요 후보' },
        { v: 'overview', t: '📅 만료 절벽', why: '잔존 기간 — 라이선스 가치의 시간 축' }] },
  ];

  function purposeOf(key) {
    for (var i = 0; i < PURPOSES.length; i++) {
      if (PURPOSES[i].key === key) return PURPOSES[i];
    }
    return null;
  }

  function currentPurpose() {
    var s = State.config && State.config.settings;
    return purposeOf(s && s.analysis_purpose);
  }

  function savePurpose(key, thenView) {
    return Api.post('/api/settings', { analysis_purpose: key || null })
      .then(function (resp) {
        State.config.settings = resp.settings;
        renderPurposeChip();
        if (thenView !== false) Views.render('purpose');
      }).catch(errToast);
  }

  // 상단바 목적 칩: 현재 분석 목적 상시 표시, 클릭 시 목적 맞춤 화면으로
  function renderPurposeChip() {
    var bar = document.getElementById('ipls-topbar');
    if (!bar) return;
    var old = document.getElementById('ipls-purpose-chip');
    if (old) old.remove();
    var cur = currentPurpose();
    var chip = Ui.el('<span id="ipls-purpose-chip" title="분석 목적 — 클릭하면 목적 맞춤 ' +
      '추천 화면으로 이동">' + (cur ? cur.icon + ' ' + Ui.esc(cur.label)
                               : '🎯 목적 선택') + '</span>');
    chip.addEventListener('click', function () { Views.render('purpose'); });
    var user = document.getElementById('ipls-userchip');
    if (user) bar.insertBefore(chip, user);
    else bar.appendChild(chip);
  }

  // 딥링크: 해당 메뉴로 이동 후 탭 라벨이 일치하는 탭을 클릭
  function gotoChart(view, tabLabel) {
    Views.render(view);
    if (!tabLabel) return;
    var btns = document.querySelectorAll('#ipls-content .view-tabs button');
    for (var i = 0; i < btns.length; i++) {
      if (btns[i].textContent.trim() === tabLabel) { btns[i].click(); return; }
    }
  }

  Views.purpose = function (content) {
    var cur = currentPurpose();
    if (!cur) {
      var c0 = card('🎯 분석 목적을 선택하세요',
        '목적을 고르면 그 목적에 맞는 차트가 우선순위와 함께 추천되고, 각 차트로 바로 이동할 수 ' +
        '있습니다. 목적은 언제든 이 화면이나 Settings 에서 바꿀 수 있으며 분석 결과 자체는 바뀌지 않습니다.');
      content.appendChild(c0.root);
      var grid = Ui.el('<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px"></div>');
      PURPOSES.forEach(function (p) {
        var cell = Ui.el('<div class="chart-holder" style="cursor:pointer;padding:14px 16px;min-height:0">' +
          '<div style="font-size:15px;font-weight:800;color:#1f3864">' + p.icon + ' ' + Ui.esc(p.label) + '</div>' +
          '<div style="font-size:12.5px;color:#46607a;margin-top:4px">' + Ui.esc(p.desc) + '</div>' +
          '<div style="font-size:11px;color:#93a5b4;margin-top:6px">주요 사용자: ' + Ui.esc(p.users) +
          ' · 핵심 차트 ' + p.primary.length + '개</div></div>');
        cell.addEventListener('click', function () {
          savePurpose(p.key);
          Ui.toast('목적이 "' + p.label + '" 로 설정되었습니다.');
        });
        grid.appendChild(cell);
      });
      c0.body.appendChild(grid);
      return;
    }
    var head = card(cur.icon + ' ' + cur.label + ' — 추천 차트',
      '분석 내용: ' + cur.desc + ' · 주요 사용자: ' + cur.users +
      '. 아래 순서가 이 목적의 권장 열람 순서입니다 — [열기]를 누르면 해당 차트로 바로 이동합니다.');
    content.appendChild(head.root);
    var chg = Ui.el('<button class="btn small">목적 변경</button>');
    chg.addEventListener('click', function () { savePurpose(null); });
    head.controls.appendChild(chg);
    if (cur.note) {
      head.body.appendChild(Ui.el('<div class="disclaimer" style="margin-bottom:8px">' +
        Ui.esc(cur.note) + '</div>'));
    }
    function chartRow(item, i, isPrimary) {
      var tr = document.createElement('tr');
      tr.innerHTML = '<td style="white-space:nowrap">' +
        (isPrimary ? '<span class="badge good">★ 핵심 ' + (i + 1) + '</span>'
                   : '<span class="badge">보조</span>') + '</td>' +
        '<td style="font-weight:700">' + Ui.esc(item.t) + '</td>' +
        '<td>' + Ui.esc(item.why) + '</td>' +
        '<td style="white-space:nowrap;color:#93a5b4;font-size:11px">' +
        Ui.esc(menuLabelOf(item.v)) + '</td><td></td>';
      var btn = Ui.el('<button class="btn small primary">열기</button>');
      btn.addEventListener('click', function () { gotoChart(item.v, item.t); });
      tr.lastElementChild.appendChild(btn);
      return tr;
    }
    var tbl = Ui.el(simpleTable(['우선순위', '차트', '이 목적에 맞는 이유', '위치', ''], []));
    var tb = tbl.querySelector('tbody');
    cur.primary.forEach(function (it, i) { tb.appendChild(chartRow(it, i, true)); });
    (cur.secondary || []).forEach(function (it, i) { tb.appendChild(chartRow(it, i, false)); });
    head.body.appendChild(tbl);
    var open1 = Ui.el('<button class="btn primary" style="margin-top:10px">▶ 1순위 차트 바로 열기 — ' +
      Ui.esc(cur.primary[0].t) + '</button>');
    open1.addEventListener('click', function () {
      gotoChart(cur.primary[0].v, cur.primary[0].t);
    });
    head.body.appendChild(open1);
  }

  function menuLabelOf(view) {
    var li = document.querySelector('#ipls-menu li[data-view="' + view + '"]');
    return li ? li.textContent.trim() : view;
  }

  /* ---------- 1. Executive Overview ---------- */
  Views.overview = function (content) {
    makeTabs(content, [
      { label: '경영 요약', render: renderOverviewMain },
      execPlusTab('📅 만료 절벽', ['expiry_cliff'],
        '특허 만료 절벽 — 언제, 누구의, 어떤 기술이 풀리는가',
        '향후 10년 만료 예정 특허를 연도×기업 적층 막대로 보여주고, 피인용 상위의 "핵심 만료 특허" ' +
        '목록을 함께 제공합니다. 경쟁사 핵심 특허의 만료 시점=진입 기회 검토 구간, 자사 핵심 특허의 ' +
        '만료=방어 공백입니다. 실제 존속 여부는 연차료 납부에 따라 달라지므로 등록원부 확인이 필요합니다.'),
      execPlusTab('💰 R&D 효율', ['rnd_efficiency'],
        'R&D 효율 사분면 — 특허비를 잘 쓰고 있는가',
        'X축=누적 출원 규모(로그), Y축=질 지수(피인용·패밀리·유효율 z-score 평균), 버블=최근 출원, ' +
        '빨강=자사. 점선(중앙값) 기준 4분면: 양·질 겸비 / 소작·정예 / 다작·저임팩트 / 양·질 모두 부족. ' +
        '자사가 어느 영역인지, 벤치마킹할 "소작·정예" 기업이 누구인지 한눈에 보입니다.'),
      execPlusTab('👤 키맨 리스크', ['keyman'],
        '키맨 리스크 — 핵심 발명자 의존도',
        '자사 특허가 소수 발명자에게 얼마나 집중되어 있는지(상위 10% 점유율·HHI)와 핵심 발명자별 ' +
        '주력 기술·마지막 출원 연도를 보여줍니다. 빨간 막대=최근 2년 출원 없음(관찰 신호 — 인과 판단 ' +
        '아님). 발명자 클릭 시 특허 이력이 열리며, 경쟁 인텔리전스의 발명자 이동 분석과 함께 보세요.'),
      execPlusTab('⏱️ 추격 시계', ['catchup'],
        '추격 시계 — 기술별 격차, 몇 년이면 따라잡나',
        '기술분류별 자사 vs 선두 기업의 누적 출원 격차와, 최근 3년 출원 속도가 유지된다는 가정에서의 ' +
        '추월 소요 연수를 표시합니다. 초록=5년 내 추월권, 노랑=추월 가능(장기), 빨강=현재 속도로는 ' +
        '불가. 어디에 투자를 집중하면 순위가 바뀌는지 보여주는 화면입니다 (산술 추정이며 예측 아님).'),
      execPlusTab('🚨 위협 레이더', ['threat'],
        '신흥 위협 레이더 — 우리 밭에 들어온 새 플레이어',
        '자사 주력 기술분류(상위 5개)에 최근 3년 내 처음 진입한 기업을 탐지합니다. X축=첫 진입 연도, ' +
        'Y축=해당 기술 출원 수, 크기=그 기업의 전체 규모, 색=기술. 큰 기업의 신규 진입=본격 투자 신호, ' +
        '작아도 빠르게 늘면 조기 경보입니다. 위협도 산식은 하단에 명시됩니다.'),
      execPlusTab('✂️ 포트폴리오 다이어트', ['pruning'],
        '포트폴리오 다이어트 — 연차료 절감 후보',
        '자사 유효특허 중 "등록 5년+ 경과, 피인용 0, 단일국, 비핵심 기술" 기준을 모두 만족하는 유지 ' +
        '재검토 후보를 선별합니다 (기준은 화면에 명시 — 기계적 선별이며 포기 권고가 아닙니다). ' +
        '연차료는 등록 연차가 오래될수록 누진되므로 경과 연차 분포가 절감 여지의 크기입니다. ' +
        '국가별 요율 데이터가 없어 금액은 계산하지 않습니다.')
    ]);
  };

  function execPlusTab(label, sectionKeys, title, help) {
    return { label: label, render: function (h) {
      analysisCard({
        analysis: 'exec-plus', holder: h, title: title, help: help,
        body: { sections: sectionKeys },
        controls: function (c, reload) {
          var sel = Ui.el('<select><option value="">자사 자동 선택</option></select>');
          ((State.filterOptions || {}).applicants || []).slice(0, 300).forEach(function (a) {
            var o = document.createElement('option'); o.value = a; o.textContent = a;
            sel.appendChild(o);
          });
          sel.addEventListener('change', function () { reload({ company: sel.value || null }); });
          var lbl = Ui.el('<span style="font-size:11.5px;color:#647b8d">자사 기준</span>');
          c.controls.prepend(sel); c.controls.prepend(lbl);
        },
        renderOk: renderExecPlus
      });
    } };
  }

  function renderExecPlus(r, c, setTarget) {
    var s = r.sections || {};
    var first = true;
    c.body.appendChild(Ui.el('<div style="font-size:12.5px;color:#46607a;margin-bottom:6px">' +
      '자사 기준: <b>' + Ui.esc(r.focal || '-') + '</b> (' + Ui.esc(r.focal_basis || '') + ')</div>'));
    function addFig(fig, tall) {
      if (!fig) return;
      var holder = Ui.el('<div class="chart-holder"' +
        (tall ? ' style="min-height:460px"' : '') + '></div>');
      c.body.appendChild(holder);
      Render.plotly(holder, fig, plotlyDrill);
      if (first) { setTarget({ kind: 'plotly', el: holder }); first = false; }
    }
    function addTable(headers, trs) {
      if (!trs.length) return;
      var tbl = Ui.el(simpleTable(headers, []));
      trs.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
      var wrap = Ui.el('<div style="overflow-x:auto;max-height:300px;overflow-y:auto"></div>');
      wrap.appendChild(tbl);
      c.body.appendChild(wrap);
    }
    function note(txt) {
      if (txt) c.body.appendChild(Ui.el('<div class="disclaimer">' + Ui.esc(txt) + '</div>'));
    }
    if (s.expiry_cliff) {
      var ec = s.expiry_cliff;
      addFig(ec.fig, true);
      c.body.appendChild(Ui.el('<div style="font-weight:700;font-size:12.5px;margin:8px 0 4px">' +
        '🔑 핵심 만료 특허 (' + Ui.esc(ec.key_basis) + ')</div>'));
      addTable(['특허', '명칭', '출원인', '기술분류', '만료 연도', '피인용'],
        (ec.key_rows || []).map(function (x) {
          var tr = document.createElement('tr');
          var td0 = document.createElement('td');
          td0.appendChild(drillCell(x.id, x.drill));
          tr.appendChild(td0);
          tr.insertAdjacentHTML('beforeend',
            '<td>' + Ui.esc(x.title) + '</td>' +
            '<td>' + Ui.esc(x.applicant) + (x.is_focal ? ' <span class="badge good">자사</span>' : '') + '</td>' +
            '<td>' + Ui.esc(x.tech) + '</td>' +
            '<td class="num">' + x.exp_year + '</td>' +
            '<td class="num">' + (x.cites !== null && x.cites !== undefined ? x.cites : '-') + '</td>');
          return tr;
        }));
      note(ec.note);
    }
    if (s.rnd_efficiency) {
      var re = s.rnd_efficiency;
      addFig(re.fig, true);
      addTable(['기업', '사분면', '누적 출원', '질 지수', '최근 출원'],
        (re.rows || []).map(function (x) {
          var tr = document.createElement('tr');
          var td0 = document.createElement('td');
          td0.appendChild(drillCell(x.company, { type: 'applicant', applicant: x.company }));
          tr.appendChild(td0);
          tr.insertAdjacentHTML('beforeend',
            '<td><span class="badge' + (x.quadrant === '양·질 겸비' ? ' good' : '') + '">' +
            Ui.esc(x.quadrant) + '</span></td>' +
            '<td class="num">' + Ui.num(x.n, 0) + '</td>' +
            '<td class="num">' + (x.quality >= 0 ? '+' : '') + x.quality + '</td>' +
            '<td class="num">' + Ui.num(x.recent_n, 0) + '</td>');
          return tr;
        }));
      note('질 지수 = ' + (re.quality_metrics || []).join(', ') + ' 의 z-score 평균 (데이터셋 내 상대비교).');
    }
    if (s.keyman) {
      var km = s.keyman;
      var grid = Ui.el('<div class="kpi-grid" style="margin-bottom:10px"></div>');
      [[Ui.num(km.n_inventors, 0) + '명', '전체 발명자'],
       [Ui.pct(km.top10_share), '상위 10% 발명자 특허 점유율'],
       [Ui.num(km.hhi, 3), '발명자 집중도 (HHI)'],
       [km.n_inactive_top + '명', '핵심 중 최근 2년 출원 없음']].forEach(function (x) {
        grid.appendChild(Ui.el('<div class="kpi"><div class="kpi-value">' + Ui.esc(x[0]) +
          '</div><div class="kpi-label">' + Ui.esc(x[1]) + '</div></div>'));
      });
      c.body.appendChild(grid);
      addFig(km.fig, true);
      addTable(['발명자', '특허 수', '점유율', '주력 기술', '마지막 출원', '상태'],
        (km.rows || []).map(function (x) {
          var tr = document.createElement('tr');
          var td0 = document.createElement('td');
          td0.appendChild(drillCell(x.inventor, x.drill));
          tr.appendChild(td0);
          tr.insertAdjacentHTML('beforeend',
            '<td class="num">' + Ui.num(x.n, 0) + '</td>' +
            '<td class="num">' + Ui.pct(x.share) + '</td>' +
            '<td>' + Ui.esc(x.top_tech) + '</td>' +
            '<td class="num">' + (x.last_year || '-') + '</td>' +
            '<td>' + (x.inactive ? '<span class="badge warn">최근 출원 없음</span>' : '활동 중') + '</td>');
          return tr;
        }));
      note(km.note);
    }
    if (s.catchup) {
      var cu = s.catchup;
      addFig(cu.fig, true);
      addTable(['기술분류', '선두', '선두/자사 건수', '격차', '속도 (선두/자사, 건·년)', '판정'],
        (cu.rows || []).map(function (x) {
          var tr = document.createElement('tr');
          var td0 = document.createElement('td');
          td0.appendChild(drillCell(x.tech, x.drill));
          tr.appendChild(td0);
          if (x.status === '선두') {
            tr.insertAdjacentHTML('beforeend',
              '<td><span class="badge good">자사 선두</span></td>' +
              '<td class="num">-</td><td class="num">' +
              (x.runner_gap !== null && x.runner_gap !== undefined ?
                '+' + Ui.num(x.runner_gap, 0) : '-') + '</td>' +
              '<td>-</td><td>2위 ' + Ui.esc(x.runner || '-') + '</td>');
          } else {
            tr.insertAdjacentHTML('beforeend',
              '<td>' + Ui.esc(x.leader) + '</td>' +
              '<td class="num">' + Ui.num(x.leader_n, 0) + ' / ' + Ui.num(x.focal_n, 0) + '</td>' +
              '<td class="num">' + Ui.num(x.gap, 0) + '</td>' +
              '<td class="num">' + x.leader_speed + ' / ' + x.focal_speed + '</td>' +
              '<td>' + Ui.esc(x.status) + '</td>');
          }
          return tr;
        }));
      note(cu.note);
    }
    if (s.threat) {
      var th = s.threat;
      addFig(th.fig, true);
      addTable(['기업', '진입 기술', '첫 진입', '해당 기술 출원', '기업 전체', '평균 피인용', '위협도'],
        (th.rows || []).map(function (x) {
          var tr = document.createElement('tr');
          var td0 = document.createElement('td');
          td0.appendChild(drillCell(x.company, x.drill));
          tr.appendChild(td0);
          tr.insertAdjacentHTML('beforeend',
            '<td>' + Ui.esc(x.tech) + '</td>' +
            '<td class="num">' + x.entry_year + '</td>' +
            '<td class="num">' + Ui.num(x.n_in_tech, 0) + '</td>' +
            '<td class="num">' + Ui.num(x.total_n, 0) + '</td>' +
            '<td class="num">' + (x.avg_cites !== null && x.avg_cites !== undefined ?
              Ui.num(x.avg_cites, 1) : '-') + '</td>' +
            '<td class="num"><b>' + x.threat + '</b></td>');
          return tr;
        }));
      note(th.note);
    }
    if (s.pruning) {
      var pr = s.pruning;
      var pgrid = Ui.el('<div class="kpi-grid" style="margin-bottom:10px"></div>');
      [[Ui.num(pr.n_candidates, 0) + '건', '유지 재검토 후보'],
       [Ui.num(pr.n_active, 0) + '건', '자사 등록·유효 특허'],
       [pr.ratio !== undefined && pr.ratio !== null ? Ui.pct(pr.ratio) : '-', '후보 비중']]
        .forEach(function (x) {
          pgrid.appendChild(Ui.el('<div class="kpi"><div class="kpi-value">' + Ui.esc(x[0]) +
            '</div><div class="kpi-label">' + Ui.esc(x[1]) + '</div></div>'));
        });
      c.body.appendChild(pgrid);
      c.body.appendChild(Ui.el('<div style="font-size:12px;color:#46607a;margin-bottom:6px">' +
        '선별 기준 (모두 만족): ' + (pr.criteria || []).map(function (cr) {
          return '<span class="badge">' + Ui.esc(cr) + '</span>';
        }).join(' ') + '</div>'));
      addFig(pr.fig_tech);
      addFig(pr.fig_age);
      addTable(['특허', '명칭', '기술분류', '등록 후 경과'],
        (pr.rows || []).map(function (x) {
          var tr = document.createElement('tr');
          var td0 = document.createElement('td');
          td0.appendChild(drillCell(x.id, x.drill));
          tr.appendChild(td0);
          tr.insertAdjacentHTML('beforeend',
            '<td>' + Ui.esc(x.title) + '</td>' +
            '<td>' + Ui.esc(x.tech) + '</td>' +
            '<td class="num">' + x.age + '년</td>');
          return tr;
        }));
      note(pr.note);
    }
    if ((r.skipped || []).length) {
      c.body.appendChild(Ui.el('<div class="disclaimer" style="margin-top:10px">생략: ' +
        r.skipped.map(function (x) {
          return Ui.esc(x.section) + ' (' + Ui.esc(x.reason) + ')';
        }).join(' · ') + '</div>'));
    }
  }

  function renderOverviewMain(content) {
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
      c.controls.appendChild(Render.excelButton('overview_patents', function () { return c.body; }, null));
    }).catch(function (e) { c.body.innerHTML = Render.statusBlock({ status: 'error', message: e.message }); });
    renderExecutiveDashboard(content);
  };

  function renderExecutiveDashboard(holder) {
    analysisCard({
      analysis: 'executive-summary', holder: holder,
      title: '경영진 전략 대시보드 — "우리는 어디에 있고, 어디에 투자해야 하는가"',
      help: '경영진의 3가지 질문에 한 화면으로 답합니다: ① 시장 내 위치(순위·점유율·성장률 격차 KPI) ' +
        '② 투자 방향(BCG 스타일 성장-점유 매트릭스) ③ 위협·기회(핵심특허 만료, 급성장 경쟁사, ' +
        '자사 부재 고성장 영역 alert). 자사는 Settings 자사명/자사 특허 여부 컬럼 기준이며 아래에서 ' +
        '직접 선택할 수도 있습니다. 특허 지표는 R&D 활동의 프록시로 매출·수익 판단을 대체하지 않습니다.',
      guide: 'BCG 매트릭스: X축=상대 시장점유율(자사 건수÷최대 경쟁사, 로그축, 1보다 오른쪽=1위), ' +
        'Y축=시장 성장률, 버블 크기=시장 규모(전체 건수). ⭐Star(우상)=지켜야 할 주력, ' +
        '❓Question(좌상)=고성장인데 아직 열위 — 투자 확대/철수를 지금 결정해야 하는 영역, ' +
        '🐄Cash Cow(우하)=성숙했지만 우위 — 효율 유지, 🐕Dog(좌하)=정리 검토 후보. ' +
        '경쟁 포지션 맵: X축=최근 성장률(오른쪽=확장 중), Y축=포트폴리오 품질, 크기=출원량, ' +
        '◇빨간 테두리=자사 — 우상단으로 갈수록 공격적 리더이고, 자사보다 오른쪽·위에 있는 ' +
        '기업이 실질 위협입니다. 버블 클릭 시 근거 특허가 열립니다.',
      controls: function (c, reload) {
        var sel = Ui.el('<select><option value="">자사 자동 선택</option></select>');
        ((State.filterOptions || {}).applicants || []).slice(0, 300).forEach(function (a) {
          var o = document.createElement('option'); o.value = a; o.textContent = a;
          sel.appendChild(o);
        });
        sel.addEventListener('change', function () { reload({ company: sel.value || null }); });
        var lbl = Ui.el('<span style="font-size:11.5px;color:#647b8d">자사 기준</span>');
        c.controls.prepend(sel); c.controls.prepend(lbl);
      },
      renderOk: function (r, c, setTarget) {
        var k = r.kpi || {};
        var grid = Ui.el('<div class="kpi-grid" style="margin-bottom:10px"></div>');
        var gapTxt = (k.growth_focal !== null && k.growth_market !== null) ?
          ((k.growth_focal - k.growth_market >= 0 ? '+' : '') +
           Ui.pct(k.growth_focal - k.growth_market)) : '-';
        [[k.rank_all ? k.rank_all + '위' : '-', '시장 순위 (누적)'],
         [k.rank_recent ? k.rank_recent + '위' : '-', '최근 3년 순위'],
         [k.share !== null && k.share !== undefined ? Ui.pct(k.share) : '-', '출원 점유율'],
         [gapTxt, '성장률: 자사-시장 격차'],
         [k.active_rate !== null && k.active_rate !== undefined ? Ui.pct(k.active_rate) : '-', '자사 유효특허 비율'],
         [k.expiring_5y_share !== null && k.expiring_5y_share !== undefined ?
           Ui.pct(k.expiring_5y_share) : '-', '5년 내 만료 비중']].forEach(function (x) {
          grid.appendChild(Ui.el('<div class="kpi"><div class="kpi-value">' + Ui.esc(x[0]) +
            '</div><div class="kpi-label">' + Ui.esc(x[1]) + '</div></div>'));
        });
        c.body.appendChild(Ui.el('<div style="font-size:12.5px;color:#46607a;margin-bottom:6px">' +
          '자사 기준: <b>' + Ui.esc(k.focal || '-') + '</b> (' + Ui.esc(k.focal_basis || '') + ')</div>'));
        c.body.appendChild(grid);
        if (r.bcg) {
          var bh = Ui.el('<div class="chart-holder tall"></div>');
          c.body.appendChild(bh);
          Render.plotly(bh, r.bcg, plotlyDrill);
          setTarget({ kind: 'plotly', el: bh });
        }
        if (r.position) {
          var ph = Ui.el('<div class="chart-holder tall"></div>');
          c.body.appendChild(ph);
          Render.plotly(ph, r.position, plotlyDrill);
          if (!r.bcg) setTarget({ kind: 'plotly', el: ph });
        }
        if ((r.alerts || []).length) {
          c.body.appendChild(Ui.el('<div style="font-weight:700;font-size:12.5px;margin:10px 0 4px">' +
            '🔔 경영 Alert</div>'));
          r.alerts.forEach(function (a) {
            var row = Ui.el('<div style="padding:6px 8px;border-bottom:1px solid #eef2f6;' +
              'display:flex;gap:8px;align-items:center"></div>');
            row.appendChild(Ui.el('<span>' + Ui.esc(a.icon || '•') + '</span>'));
            var span = Ui.el('<span class="clickable" style="flex:1"></span>');
            span.textContent = a.text;
            span.addEventListener('click', function () { Drill.open(a.drill, a.text.slice(0, 40)); });
            row.appendChild(span);
            c.body.appendChild(row);
          });
        }
      }
    });
  }

  /* ---------- 차트 해석 가이드 (X/Y축 의미 + 읽는 법) ---------- */
  var CHART_GUIDE = {
    'technology-network':
      '노드=기술분류(크기=특허 건수, 테두리 초록=최근 성장·빨강=감소·회색=판단 불가), ' +
      '선=두 분류가 한 특허에 함께 부여된 동시분류 관계(두께=결합 강도 Jaccard). ' +
      '읽는 법: 가운데에 여러 노드와 굵게 연결된 노드가 기술 융합의 허브입니다. ' +
      '노드는 드래그로 재배치할 수 있고, 선을 클릭하면 해당 조합의 근거 특허가 열립니다.',
    'emerging-combinations':
      'X축=조합 누적 특허 수(로그 스케일, 오른쪽일수록 이미 성숙한 조합), ' +
      'Y축=최근 3년 성장률(위일수록 급성장), 버블 크기=신규 진입 출원인 수, ' +
      '색=Lift(우연 대비 결합 강도, 클수록 의미 있는 융합). ' +
      '읽는 법: 좌상단(적은 누적×고성장)의 크고 진한 버블이 새로 뜨는 기술융합 후보이고, ' +
      '우상단은 이미 검증된 핵심 융합, 우하단은 성숙·정체 조합입니다.',
    'lifecycle':
      'X축=기술 성숙도(경과연수·누적건수를 0~1로 정규화, 오른쪽=오래되고 큰 기술), ' +
      'Y축=성장 모멘텀(최근 성장률·신규 출원인을 0~1로 정규화, 위=탄력 강함), ' +
      '버블 크기=유효 특허 수, 색=경쟁 강도(출원인 수), 화살표=전년 대비 이동 방향. ' +
      '읽는 법: 좌상=Emerging(초기 성장), 우상=Growing 핵심, 우하=Mature/Declining. ' +
      '우하에서 위로 되돌아오는 기술은 Re-emerging(재부상) 신호입니다.',
    'technology-transition':
      '왼쪽 노드=이전 기간의 기술분류, 오른쪽 노드=다음 기간의 기술분류, ' +
      '띠 두께=전이량, 색=대분류. ' +
      '읽는 법: 굵은 띠가 모여드는 오른쪽 분류가 포트폴리오의 중심이 이동해 가는 ' +
      '목적지입니다. 띠를 클릭하면 관련 특허가 열립니다.',
    'trajectory':
      '각 점=한 기업의 특정 연도 기술 포트폴리오 위치(주성분 2차원 좌표, 절대 단위 없음), ' +
      '화살표=연도 순서의 이동, 점 크기=그 해 유효 특허 수. ' +
      '읽는 법: 점 사이 거리=포트폴리오 구성의 차이이므로, 궤적이 길게 움직인 기업은 ' +
      '전략을 재편 중이고 제자리에 머무는 기업은 일관된 전략입니다. ' +
      '두 기업의 점이 가까우면 유사한 기술 구성을 갖고 있다는 뜻입니다.',
    'company-dna':
      '레이더의 각 축=12개 전략 지표를 비교 기업 사이에서 0~1로 표준화한 점수(1=최고), ' +
      '히트맵일 때는 색이 진할수록 높음. Hover 에 원값이 함께 표시됩니다. ' +
      '읽는 법: 도형이 전체적으로 넓은 기업=전방위 강자, 특정 축만 뾰족하면 그 영역 특화. ' +
      '평행좌표는 세로축=지표, 꺾은선 1개=기업 1개입니다.',
    'lead-lag':
      '노드=기업(크기=특허 수), 화살표=시계열상 선행→추종 방향, 두께=관계 강도, ' +
      '라벨=평균 시차(년). ' +
      '읽는 법: A→B 화살표는 "A의 출원 증가 후 일정 시차를 두고 B가 증가하는 패턴이 ' +
      '여러 기술분류에서 반복 관측됨"을 뜻합니다. 통계적 선행 신호이며 인과관계·모방의 ' +
      '증거가 아닙니다.',
    'opportunity':
      'X축=매력도(성장률·신규 진입·조합 증가·키워드·과제 반복·인접성의 가중 기하평균, 0~1), ' +
      'Y축=진입 가능성(1-권리장벽, 0~1), 버블 크기=관련 특허 수, 색=권리장벽(빨강=높음), ' +
      '◇ 마커=자사 역량 보유 영역. ' +
      '읽는 법: 우상단=우선 공략 후보, 우하단=매력적이지만 장벽이 높아 제휴·라이선스 검토 ' +
      '대상, 좌측=현재 매력도가 낮은 영역입니다.',
    'problem-solution':
      '행(Y축)=해결과제, 열(X축)=해결수단, 셀 색=최근 성장률(초록=성장, 빨강=감소), ' +
      'Hover=건수·유효비율·상위 출원인. ' +
      '읽는 법: 값이 없는 빈 셀=아직 시도되지 않은 과제×수단 조합(공백 후보)이며, ' +
      '성장 중인 셀 주변의 빈 셀이 특히 유망합니다. 셀을 클릭하면 특허 목록·추이·대표 ' +
      '청구항 패널이 열립니다.',
    'citation-diffusion':
      '막대: X축=Influence Score(직·간접 피인용, 타 분류/기업 확산, 패밀리 확장, 권리 ' +
      '유지의 표준화 가중합), Y축=특허. Sankey: 핵심특허→기술분류→주요 출원인으로 흐르는 ' +
      '띠(두께=피인용 가중)가 영향력 전파 경로입니다. ' +
      '읽는 법: Influence 상위 특허 중 만료 임박 특허는 만료 후 설계 자유도가 커지는 ' +
      '기회 신호입니다.',
    'claim-density':
      '좌표=독립청구항의 의미 유사도 배치(가까울수록 유사한 권리범위, 축 자체는 단위 없음), ' +
      '등고선 붉은 영역=청구항이 밀집된 곳(권리 경쟁 치열), 점 크기=피인용, 색=출원인, ' +
      '불투명한 점=유효 권리, 테두리 굵은 점=등록특허. ' +
      '읽는 법: 밀집 영역에 타사 유효 특허가 몰려 있으면 우선 검토 대상이고, 밀도가 낮은 ' +
      '영역이 상대적으로 여유 있는 공간입니다. FTO 판단을 대체하지 않습니다.',
    'inventor-mobility':
      '노드=기업, 화살표=발명자 이동 방향(두께=이동 인원 수), 색=대표 기술분류. ' +
      '읽는 법: A→B로 굵은 화살표가 이어지면 A에서 B로 인력·기술이 이동했다는 신호입니다. ' +
      '동명이인 가능성 때문에 신뢰도 점수 기반 추정이며, 낮은 신뢰도의 "추정 이동"은 ' +
      '기본적으로 제외됩니다.',
    'classification-quality':
      'Confusion Map: 행·열=기술분류, 셀 값=두 분류 중심의 의미 유사도(임베딩) 또는 중복 ' +
      '특허 비율. 붉은 셀=경계가 모호한 분류쌍(통합 검토 후보), 파란 셀=분리 명확. ' +
      '응집도 막대: 값이 낮은 분류는 서로 다른 기술이 섞여 있어 분리 검토 대상입니다.'
  };

  /* ---------- 헬퍼: 표준 분석 카드 ---------- */
  function analysisCard(opts) {
    // opts: {analysis, title, help, guide?, holder, body, renderOk(...), controls(...)}
    var c = card(opts.title, opts.help);
    opts.holder.appendChild(c.root);
    if (!availabilityGuard(opts.analysis, c.body)) return null;
    var chartTarget = null;
    c.controls.appendChild(Render.chartButtons(function () { return chartTarget; },
      opts.analysis.replace(/-/g, '_')));
    c.controls.appendChild(Render.excelButton(opts.analysis, function () { return c.body; }, opts.drill || null));
    function reload(extraBody) {
      var body = Object.assign({ filters: State.filters }, opts.body || {}, extraBody || {});
      disposeCharts(c.body);
      c.body.innerHTML = '<div class="status-empty">불러오는 중…</div>';
      Api.post('/api/' + opts.analysis, body, opts.title + ' 계산 중…').then(function (r) {
        State.lastResults[opts.analysis] = r;
        c.body.innerHTML = '';
        if (r.status !== 'ok') { c.body.innerHTML = Render.statusBlock(r); return; }
        opts.renderOk(r, c, function (t) { chartTarget = t; });
        var guideText = opts.guide || CHART_GUIDE[opts.analysis];
        if (guideText) {
          c.body.appendChild(Ui.el('<div class="chart-guide"><b>📖 차트 해석</b>' +
            Ui.esc(guideText) + '</div>'));
        }
        c.body.appendChild(Insight.box(r, opts.analysis));
        c.body.appendChild(Insight.aiPanel(opts.analysis, r, opts.title + ' — ' + (c.desc || '')));
        paginateCharts(c.body);  // 카드에 차트가 여러 개면 한 화면 한 차트 페이저
      }).catch(function (e) {
        c.body.innerHTML = Render.statusBlock({ status: 'error', message: e.message });
      });
    }
    if (opts.controls) opts.controls(c, reload);
    reload();
    return { card: c, reload: reload };
  }

  function plotlyDrill(drill) { Drill.open(drill, '근거 특허'); }

  /* ---------- 차트 페이저: 카드에 차트가 여러 개면 한 화면에 한 개씩 ----------
     카드 본문의 최상위 자식들을 "차트를 포함한 요소 = 새 페이지 시작, 그 뒤의
     표·설명은 같은 페이지" 규칙으로 묶는다. 차트 앞의 요소(컨트롤 등)와 차트
     해석·인사이트(마지막 그룹의 chart-guide/insight 이후)는 항상 표시한다.
     '전체 보기' 토글로 기존 세로 나열도 선택 가능 (선호는 브라우저에 기억). */
  var PAGER_PREF_KEY = 'ipls-chart-pager-off';

  function paginateCharts(body) {
    if (body.querySelectorAll('.chart-holder, .cy-holder').length < 2) return;
    var kids = Array.prototype.slice.call(body.children);
    // 꼬리(상시 표시): 첫 insight-box/ai-panel 부터 끝까지 + 그 직전의
    // 카드 공통 chart-guide. 차트 사이의 개별 chart-guide 는 그 차트 페이지에 속함.
    var tailStart = kids.length;
    for (var ti = 0; ti < kids.length; ti++) {
      if (kids[ti].classList.contains('insight-box') ||
          kids[ti].classList.contains('ai-panel')) { tailStart = ti; break; }
    }
    if (tailStart > 0 && kids[tailStart - 1].classList &&
        kids[tailStart - 1].classList.contains('chart-guide')) {
      tailStart--;
    }
    var pages = [], current = null, pending = [];
    kids.slice(0, tailStart).forEach(function (el) {
      var hasChart = el.classList.contains('chart-holder') ||
        el.classList.contains('cy-holder') ||
        (el.querySelector && el.querySelector('.chart-holder, .cy-holder'));
      if (el.classList.contains('sec-head')) {
        // 섹션 제목은 다음 차트 페이지의 머리로 붙인다
        pending.push(el); current = null; return;
      }
      if (hasChart) {
        current = { els: pending.concat([el]) };
        pending = [];
        pages.push(current);
      } else if (current) { current.els.push(el); }
      else if (pages.length || pending.length) { pending.push(el); }
      // 첫 섹션 제목·첫 차트 이전 요소는 그대로 상시 표시 (컨트롤 등)
    });
    if (pending.length && pages.length) {
      // 마지막 섹션 제목 뒤에 차트가 없던 경우: 마지막 페이지에 붙여 표시
      pages[pages.length - 1].els = pages[pages.length - 1].els.concat(pending);
    }
    if (pages.length < 2) return;

    function pageTitle(pg, i) {
      if (pg.els[0].classList.contains('sec-head')) {
        var ht = pg.els[0].textContent.trim();
        if (ht) return ht.slice(0, 42);
      }
      var gd = null;
      for (var j = 0; j < pg.els.length && !gd; j++) {
        gd = pg.els[j].classList.contains('ipls-chart') ? pg.els[j]
          : (pg.els[j].querySelector && pg.els[j].querySelector('.ipls-chart'));
      }
      var t = gd && gd.layout && gd.layout.title &&
        (gd.layout.title.text || gd.layout.title);
      if (typeof t === 'string' && t.trim()) {
        return String(t).replace(/<[^>]*>/g, '').slice(0, 42);
      }
      for (var k = 0; k < pg.els.length; k++) {
        if (pg.els[k].classList.contains('cy-holder') ||
            (pg.els[k].querySelector && pg.els[k].querySelector('.cy-holder'))) {
          return '네트워크 차트 ' + (i + 1);
        }
      }
      return '차트 ' + (i + 1);
    }

    var nav = Ui.el('<div class="chart-pager"></div>');
    var prev = Ui.el('<button class="btn small">◀ 이전</button>');
    var sel = Ui.el('<select style="max-width:340px"></select>');
    var next = Ui.el('<button class="btn small">다음 ▶</button>');
    var count = Ui.el('<span class="pager-count"></span>');
    var all = Ui.el('<label class="pager-all"><input type="checkbox">전체 보기 (세로 나열)</label>');
    pages.forEach(function (pg, i) {
      var o = document.createElement('option');
      o.value = i;
      o.textContent = (i + 1) + '. ' + pageTitle(pg, i);
      sel.appendChild(o);
    });
    nav.appendChild(prev); nav.appendChild(sel); nav.appendChild(next);
    nav.appendChild(count); nav.appendChild(all);
    body.insertBefore(nav, pages[0].els[0]);

    var idx = 0;
    var showAll = localStorage.getItem(PAGER_PREF_KEY) === '1';
    all.querySelector('input').checked = showAll;
    function apply() {
      pages.forEach(function (pg, i) {
        pg.els.forEach(function (el) {
          el.style.display = (showAll || i === idx) ? '' : 'none';
        });
      });
      sel.value = String(idx);
      count.textContent = showAll ? '전체 ' + pages.length + '개'
        : (idx + 1) + ' / ' + pages.length;
      prev.disabled = showAll || idx === 0;
      next.disabled = showAll || idx === pages.length - 1;
      sel.disabled = showAll;
      // 보이게 된 차트만 재배치 — 숨김 plot 에 resize 를 걸면 Plotly 가
      // 거부(콘솔 오류)하므로 현재 페이지의 요소만 대상
      pages.forEach(function (pg, i) {
        if (!showAll && i !== idx) return;
        pg.els.forEach(function (el) {
          try {
            var gds = el.classList.contains('ipls-chart') ? [el]
              : Array.prototype.slice.call(
                  el.querySelectorAll ? el.querySelectorAll('.ipls-chart') : []);
            gds.forEach(function (gd) {
              if (window.Plotly && Plotly.Plots && Plotly.Plots.resize) {
                Plotly.Plots.resize(gd);
              }
            });
            var cys = el.classList.contains('cy-holder') ? [el]
              : Array.prototype.slice.call(
                  el.querySelectorAll ? el.querySelectorAll('.cy-holder') : []);
            cys.forEach(function (ch) {
              if (ch.__iplsCy && ch.__iplsCy.resize) ch.__iplsCy.resize();
            });
          } catch (e) { /* 재배치 실패는 표시에 치명적이지 않음 */ }
        });
      });
    }
    prev.addEventListener('click', function () { if (idx > 0) { idx--; apply(); } });
    next.addEventListener('click', function () {
      if (idx < pages.length - 1) { idx++; apply(); }
    });
    sel.addEventListener('change', function () { idx = +sel.value || 0; apply(); });
    all.querySelector('input').addEventListener('change', function (ev) {
      showAll = ev.target.checked;
      localStorage.setItem(PAGER_PREF_KEY, showAll ? '1' : '0');
      apply();
    });
    apply();
  }

  /* 출원인 선택 컨트롤 (공용) — analysisCard 의 controls 로 사용.
     선택 시 body 에 company 를 실어 재계산하며, 공동출원 건도 포함 매칭된다. */
  function companySelectControls(labelText) {
    return function (c, reload) {
      var sel = Ui.el('<select><option value="">전체 출원인</option></select>');
      ((State.filterOptions || {}).applicants || []).slice(0, 300).forEach(function (a) {
        var o = document.createElement('option'); o.value = a; o.textContent = a;
        sel.appendChild(o);
      });
      sel.addEventListener('change', function () {
        reload({ company: sel.value || null });
      });
      var lbl = Ui.el('<span style="font-size:11.5px;color:#647b8d">' +
        Ui.esc(labelText || '출원인 선택') + '</span>');
      c.controls.prepend(sel); c.controls.prepend(lbl);
    };
  }

  /* 복수 출원인 선택 컨트롤 (공용) — '회사 추가…'로 골라 칩으로 표시, 칩 클릭=제거.
     선택 시 body 에 companies 배열을 실어 재계산한다. */
  function multiCompanyControls(labelText) {
    return function (c, reload) {
      var chosen = [];
      var chips = Ui.el('<span style="display:inline-flex;gap:4px;flex-wrap:wrap;align-items:center"></span>');
      var sel = Ui.el('<select><option value="">회사 추가… (미선택=전체)</option></select>');
      ((State.filterOptions || {}).applicants || []).slice(0, 300).forEach(function (a) {
        var o = document.createElement('option'); o.value = a; o.textContent = a;
        sel.appendChild(o);
      });
      function renderChips() {
        chips.innerHTML = '';
        chosen.forEach(function (name) {
          var chip = Ui.el('<span class="badge" style="cursor:pointer" title="클릭하여 제거">' +
            Ui.esc(name) + ' ✕</span>');
          chip.addEventListener('click', function () {
            chosen = chosen.filter(function (x) { return x !== name; });
            renderChips();
            reload({ companies: chosen.length ? chosen.slice() : null });
          });
          chips.appendChild(chip);
        });
      }
      sel.addEventListener('change', function () {
        if (sel.value && chosen.indexOf(sel.value) < 0) {
          chosen.push(sel.value);
          renderChips();
          reload({ companies: chosen.slice() });
        }
        sel.value = '';
      });
      c.controls.prepend(chips);
      c.controls.prepend(sel);
      c.controls.prepend(Ui.el('<span style="font-size:11.5px;color:#647b8d">' +
        Ui.esc(labelText || '회사 선택') + '</span>'));
    };
  }

  /* ---------- 1.5 공용 탭 팩토리 (전체 동향·기술 분석·심층 시그널 공용) ---------- */
    function statsTab(title, help, keys, guide, withCompany) {
      return function (h) {
        analysisCard({
          analysis: 'basic-stats', holder: h, title: title, help: help, guide: guide,
          controls: withCompany ? companySelectControls('출원인 선택') : undefined,
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
              if (r.chart_insights && r.chart_insights[key]) {
                c.body.appendChild(miniInsight(r.chart_insights[key]));
              }
            });
          }
        });
      };
    }
    function deepTab(label, sectionKeys, title, help) {
      /* 심층 시그널을 특성별 탭으로 분할 — 각 탭은 해당 섹션만 계산·표시하고
         인사이트도 그 범위로 한정된다 (백엔드 sections 파라미터). */
      return { label: label, render: function (h) {
        analysisCard({
          analysis: 'wips-deep', holder: h, title: title + ' (출원인 선택 가능)',
          controls: companySelectControls('출원인 선택'),
          help: help + ' 해당 컬럼이 매핑된 섹션만 계산되고 나머지는 하단에 사유와 함께 ' +
            '생략됩니다. 상단에서 출원인을 선택하면 그 회사 문헌(공동출원 포함)만으로 ' +
            '재계산됩니다. 모든 신호는 상관 관찰이며 인과·법률 판단이 아닙니다.',
          body: { sections: sectionKeys },
          renderOk: renderDeepSections
        });
      } };
    }
    function deepPlusTab(label, sectionKeys, title, help) {
      return { label: label, render: function (h) {
        analysisCard({
          analysis: 'deep-plus', holder: h, title: title + ' (출원인 선택 가능)',
          controls: companySelectControls('출원인 선택'),
          help: help + ' 해당 컬럼이 매핑된 섹션만 계산되고 나머지는 사유와 함께 생략됩니다. ' +
            '상단에서 출원인을 선택하면 그 회사 문헌(공동출원 포함)만으로 재계산됩니다. ' +
            '모든 신호는 상관 관찰이며 인과·법률 판단이 아닙니다.',
          body: { sections: sectionKeys },
          renderOk: renderDeepPlus
        });
      } };
    }

    function renderDeepPlus(r, c, setTarget) {
      var s = r.sections || {};
      var first = true;
      function head(txt) {
        c.body.appendChild(Ui.el('<div class="sec-head" style="font-weight:700;' +
          'font-size:13px;margin:14px 0 4px;border-top:1px solid #e8eff5;' +
          'padding-top:10px">' + Ui.esc(txt) + '</div>'));
      }
      function addFig(fig, capText) {
        if (!fig) return null;
        var holder = Ui.el('<div class="chart-holder"></div>');
        c.body.appendChild(holder);
        Render.plotly(holder, fig, plotlyDrill);
        if (first) { setTarget({ kind: 'plotly', el: holder }); first = false; }
        if (capText) c.body.appendChild(chartCap(capText));
        return holder;
      }
      function addTable(headers, trs) {
        if (!trs.length) return;
        var tbl = Ui.el(simpleTable(headers, []));
        trs.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
        var wrap = Ui.el('<div style="overflow-x:auto;max-height:280px;overflow-y:auto"></div>');
        wrap.appendChild(tbl);
        c.body.appendChild(wrap);
      }
      function note(txt) {
        if (txt) c.body.appendChild(Ui.el('<div class="disclaimer">' + Ui.esc(txt) + '</div>'));
      }
      function idRow(x, extraCells) {
        var tr = document.createElement('tr');
        var td0 = document.createElement('td');
        td0.appendChild(drillCell(x.id, x.drill));
        tr.appendChild(td0);
        tr.insertAdjacentHTML('beforeend', extraCells);
        return tr;
      }
      if (s.license) {
        var lc = s.license;
        head('🤝 실시권(라이선스) 신호 — 상업화의 직접 증거');
        c.body.appendChild(Ui.el('<div style="color:#46607a;font-size:12.5px;margin-bottom:6px">' +
          '실시권 설정 특허 <b>' + Ui.num(lc.n_licensed, 0) + '건</b> (' + Ui.pct(lc.ratio) + ')' +
          (lc.quality ? ' · 평균 피인용: 실시권 <b>' + Ui.num(lc.quality.licensed_avg, 1) +
            '</b> vs 일반 <b>' + Ui.num(lc.quality.other_avg, 1) + '</b>' : '') + '</div>'));
        addFig(lc.fig_tech,
          'X축=라이선스율(실시권 설정 비율), Y축=기술분류. 읽는 법: 라이선스율이 높은 기술은 ' +
          '시장에서 실제로 돈을 내고 쓰는 기술 — 특허의 상업 가치가 검증된 영역입니다.');
        addFig(lc.fig_comp, null);
        addTable(['특허', '명칭', '출원인', '기술분류', '실시권자 수'],
          (lc.rows || []).map(function (x) {
            return idRow(x, '<td>' + Ui.esc(x.title) + '</td><td>' + Ui.esc(x.applicant) +
              '</td><td>' + Ui.esc(x.tech) + '</td><td class="num">' +
              (x.licensees !== null && x.licensees !== undefined ? x.licensees : '-') + '</td>');
          }));
        note(lc.note);
      }
      if (s.sep) {
        var sp = s.sep;
        head('📡 표준특허(SEP) 현황 — 선언 ' + Ui.num(sp.n_sep, 0) + '건');
        addFig(sp.fig_org,
          'X축=선언 특허 수, Y축=표준화기구. 읽는 법: 표준 필수특허 선언은 로열티 협상력의 ' +
          '근거입니다 — 선언은 자기 신고이며 필수성 검증은 아닙니다.');
        addFig(sp.fig_comp, null);
        addFig(sp.fig_year, null);
        addTable(['특허', '출원인', '표준화기구', '표준번호', '선언일'],
          (sp.rows || []).map(function (x) {
            return idRow(x, '<td>' + Ui.esc(x.applicant) + '</td><td>' + Ui.esc(x.org) +
              '</td><td>' + Ui.esc(x.std_no) + '</td><td>' + Ui.esc(x.declared) + '</td>');
          }));
        note(sp.note);
      }
      if (s.assignment) {
        var am = s.assignment;
        head('🔄 권리변동 타임라인 — 양도 기록 ' + Ui.num(am.n_assign, 0) + '건');
        addFig(am.fig_year,
          'X축=양도 연도, 색=양도유형. 읽는 법: 거래가 몰린 시기·유형이 시장 이벤트의 흔적입니다. ' +
          '담보설정은 특허를 담보로 한 자금 조달의 관찰 신호입니다.');
        addFig(am.fig_buyers, null);
        addTable(['특허', '양도일', '양도인', '양수인', '유형', '기술분류'],
          (am.rows || []).map(function (x) {
            return idRow(x, '<td style="white-space:nowrap">' + Ui.esc(x.date) + '</td><td>' +
              Ui.esc(x.assignor) + '</td><td>' + Ui.esc(x.assignee) + '</td><td>' +
              Ui.esc(x.type) + '</td><td>' + Ui.esc(x.tech) + '</td>');
          }));
        note(am.note);
      }
      if (s.rejection) {
        var rj = s.rejection;
        head('🚫 거절 사유 인텔리전스 — 출원 전략 개선 지점');
        addFig(rj.fig_reason,
          'X축=건수, Y축=거절 사유 유형(키워드 자동 분류). 읽는 법: 1위 사유가 우리 분야 출원이 ' +
          '가장 자주 부딪히는 벽입니다 — 진보성이면 선행조사 강화, 기재불비면 명세서 품질 점검.');
        addFig(rj.fig_comp, null);
        if (rj.reexam_rate !== null && rj.reexam_rate !== undefined) {
          c.body.appendChild(Ui.el('<div style="color:#46607a;font-size:12.5px;margin:6px 0">' +
            '재심사청구율: <b>' + Ui.pct(rj.reexam_rate) + '</b> — 거절 후 재도전 비율</div>'));
        }
        note(rj.note);
      }
      if (s.science) {
        var sc = s.science;
        head('🔬 과학 연계성 (Science Linkage) — 평균 NPL 인용 ' + Ui.num(sc.avg_all, 1) + '건');
        addFig(sc.fig_tech,
          'X축=평균 비특허문헌(논문 등) 인용 수, Y축=기술분류. 읽는 법: NPL 인용이 많은 기술은 ' +
          '기초연구에서 갓 나온 신기술 신호 — 장기 관점의 원천 기술 후보입니다. ' +
          '막대 클릭 시 그 분류에서 NPL 을 실제 인용한 특허만 열립니다.');
        var scHolder = addFig(sc.fig_comp,
          'X축=평균 비특허문헌 인용 수, Y축=출원인. 읽는 법: 평균이 높은 회사=논문 기반 ' +
          '원천 연구형, 낮은 회사=응용·개량형. 막대 클릭 시 그 회사(공동출원 포함)의 ' +
          'NPL 인용 특허만 열립니다.');
        if (scHolder && (sc.by_comp || []).length) {
          scHolder.__iplsExtraSheets = [{
            name: '기업별 과학 근접도',
            columns: ['출원인', '평균 NPL 인용 수', '표본 특허 수', 'NPL 인용(1건 이상) 특허 수'],
            rows: sc.by_comp.map(function (x) {
              return [x.company, x.mean_npl, x.n, x.n_cited];
            }),
            desc: '기업별 과학 근접도 차트의 원천 데이터 — 평균 NPL 인용 수(비특허문헌 ' +
              '수 컬럼 기준), 표본=NPL 값이 해석된 그 회사 특허 수, 마지막 열=그중 ' +
              'NPL 을 1건 이상 인용한 특허 수.'
          }];
        }
        addTable(['특허', '명칭', '출원인', '기술분류', 'NPL 인용'],
          (sc.rows || []).map(function (x) {
            return idRow(x, '<td>' + Ui.esc(x.title) + '</td><td>' + Ui.esc(x.applicant) +
              '</td><td>' + Ui.esc(x.tech) + '</td><td class="num">' + x.npl + '</td>');
          }));
        note(sc.note);
      }
      if (s.examiner) {
        var ex = s.examiner;
        head('🧑‍⚖️ 심사관 인텔리전스 (내부 참고용)');
        addFig(ex.fig,
          'X축=담당 건수, Y축=심사관. hover 에 등록률·평균 OA 횟수. 읽는 법: 데이터셋 표본 ' +
          '기준의 참고 정보이며 심사관 개인의 전체 성향과 다를 수 있습니다.');
        addTable(['심사관', '담당 건수', '등록률', '평균 OA'],
          (ex.rows || []).map(function (x) {
            var tr = document.createElement('tr');
            tr.insertAdjacentHTML('beforeend',
              '<td>' + Ui.esc(x.examiner) + '</td><td class="num">' + Ui.num(x.n, 0) + '</td>' +
              '<td class="num">' + (x.grant_rate !== null && x.grant_rate !== undefined ?
                Ui.pct(x.grant_rate) : '-') + '</td>' +
              '<td class="num">' + (x.avg_oa !== null && x.avg_oa !== undefined ?
                x.avg_oa : '-') + '</td>');
            return tr;
          }));
        note(ex.note);
      }
      if ((r.skipped || []).length) {
        c.body.appendChild(Ui.el('<div class="disclaimer" style="margin-top:10px">생략: ' +
          r.skipped.map(function (x) {
            return Ui.esc(x.section) + ' (' + Ui.esc(x.reason) + ')';
          }).join(' · ') + '</div>'));
      }
    }

    function renderDeepSections(r, c, setTarget) {
            var s = r.sections || {};
            var first = true;
            function head(txt) {
              c.body.appendChild(Ui.el('<div class="sec-head" style="font-weight:700;' +
                'font-size:13px;margin:14px 0 4px;border-top:1px solid #e8eff5;' +
                'padding-top:10px">' + Ui.esc(txt) + '</div>'));
            }
            function addFig(fig, capText, tall) {
              if (!fig) return;
              var holder = Ui.el('<div class="chart-holder"' +
                (tall ? ' style="min-height:460px"' : '') + '></div>');
              c.body.appendChild(holder);
              Render.plotly(holder, fig, plotlyDrill);
              if (first) { setTarget({ kind: 'plotly', el: holder }); first = false; }
              if (capText) c.body.appendChild(chartCap(capText));
            }
            function addTable(headers, rows) {
              if (!rows.length) return;
              var tbl = Ui.el(simpleTable(headers, []));
              rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
              var wrap = Ui.el('<div style="overflow-x:auto;max-height:280px;overflow-y:auto"></div>');
              wrap.appendChild(tbl);
              c.body.appendChild(wrap);
            }
            if (s.survival) {
              head('① 연차료 생존곡선 — 기업 스스로 매긴 특허 가치');
              addFig(s.survival.fig,
                'X축=등록 후 경과 연수, Y축=권리 유지 비율(Kaplan-Meier, 유효특허는 관측 중단 처리). ' +
                '읽는 법: 곡선이 빨리 떨어지는 분류는 출원은 해도 연차료를 일찍 포기하는 "출원 실적용" ' +
                '의심 영역, 끝까지 높게 유지되는 분류가 진짜 사업 핵심입니다. 이 순위는 출원건수 순위와 ' +
                '크게 다를 수 있습니다.');
              addFig(s.survival.fig_company, null);
              addTable(['기술분류', '표본', '5년 생존율', '10년', '18년(완주)', '중위 생존연수'],
                (s.survival.techs || []).map(function (x) {
                  var tr = document.createElement('tr');
                  var td0 = document.createElement('td');
                  td0.appendChild(drillCell(x.tech, x.drill));
                  tr.appendChild(td0);
                  tr.insertAdjacentHTML('beforeend',
                    '<td class="num">' + Ui.num(x.n, 0) + '</td>' +
                    '<td class="num">' + Ui.pct(x.surv_5y) + '</td>' +
                    '<td class="num">' + Ui.pct(x.surv_10y) + '</td>' +
                    '<td class="num">' + Ui.pct(x.surv_18y) + '</td>' +
                    '<td class="num">' + (x.median !== null ? x.median + '년' : '미도달(장수)') + '</td>');
                  return tr;
                }));
            }
            if (s.market_entry) {
              head('② 지정국 진입 순서 — 시장 베팅 지도');
              addFig(s.market_entry.fig,
                '행=기업, 열=국가, 색=우선일 이후 평균 진입 시차(개월, 낮을수록 먼저 베팅한 시장). ' +
                '읽는 법: 1순위 진입국이 그 기업이 가장 중요하게 본 시장입니다. 최근 1순위가 바뀐 ' +
                '기업(아래 표 "전환")은 생산·판매 전략 전환 신호일 수 있습니다.');
              addTable(['기업', '복수국 패밀리', '1순위 진입국(전체)', '비중', '최근 1순위', '전환'],
                (s.market_entry.first_entries || []).map(function (x) {
                  var tr = document.createElement('tr');
                  tr.insertAdjacentHTML('beforeend',
                    '<td>' + Ui.esc(x.company) + '</td>' +
                    '<td class="num">' + Ui.num(x.n_families, 0) + '</td>' +
                    '<td>' + Ui.esc(x.first_country) + '</td>' +
                    '<td class="num">' + Ui.pct(x.first_share) + '</td>' +
                    '<td>' + Ui.esc(x.recent_first || '-') + '</td>' +
                    '<td>' + (x.shifted ? '<span class="badge warn">전환</span>' : '-') + '</td>');
                  return tr;
                }));
            }
            if (s.agent) {
              head('③ 대리인 전환 시그널 — 관찰된 변화 (인과 아님)');
              addFig(s.agent.fig,
                '행=기업, 열=연도, 색=그 해 처음 쓰는 대리인의 출원 비중. 읽는 법: 특정 연도에 ' +
                '갑자기 진해지면 대리인 교체·추가가 일어난 해입니다. 신규 사업 진입이나 소송 대비의 ' +
                '선행 신호일 수 있으나 상관 관찰일 뿐이므로 "관찰된 변화"로만 해석하세요.');
              addTable(['기업', '연도', '신규 대리인', '비중', '이전 주 대리인', '주요 기술분류', '건수'],
                (s.agent.signals || []).map(function (x) {
                  var tr = document.createElement('tr');
                  tr.insertAdjacentHTML('beforeend',
                    '<td>' + Ui.esc(x.company) + '</td><td class="num">' + x.year + '</td>' +
                    '<td>' + Ui.esc(x.new_agent) + '</td>' +
                    '<td class="num">' + Ui.pct(x.share) + '</td>' +
                    '<td>' + Ui.esc(x.prior_main) + '</td><td>' + Ui.esc(x.tech) + '</td>' +
                    '<td class="num">' + x.n + '</td>');
                  return tr;
                }));
            }
            if (s.examiner_eye) {
              head('④ 심사관의 눈 — OA 인용 vs 출원인측 인용');
              addFig(s.examiner_eye.fig,
                'X축=출원인측 인용 평균(WIPS 자기인용 문헌번호 기준), Y축=심사관(OA) 인용 평균, 점=기술분류. 읽는 법: ' +
                '점선(대각선) 위쪽으로 크게 벗어난 빨간 분류는 심사관이 본 선행기술은 많은데 ' +
                '출원인들은 적게 인용하는 영역 = 선행기술 과소평가 → 등록되어도 무효 리스크가 ' +
                '높을 수 있는 영역입니다.');
            }
            if (s.expedited) {
              head('⑤ 우선심사·조기공개 — 사업화 긴급도 자기 신고');
              addFig(s.expedited.fig,
                'X축=출원연도, Y축=기술분류, 크기=출원 수, 색=우선심사 비율. 읽는 법: 우선심사에는 ' +
                '비용과 명분이 들므로 비율 급등은 사업화 임박의 자기 신고입니다. 최근 진한 버블이 ' +
                '커지는 분류는 1~2년 내 제품 출시 가능성이 높은 영역입니다.');
              addTable(['기술분류', '최근 우선심사 비율', '이전 비율', '변화', '최근 표본'],
                (s.expedited.surge || []).map(function (x) {
                  var tr = document.createElement('tr');
                  var td0 = document.createElement('td');
                  td0.appendChild(drillCell(x.tech, x.drill));
                  tr.appendChild(td0);
                  tr.insertAdjacentHTML('beforeend',
                    '<td class="num">' + Ui.pct(x.recent_ratio) + '</td>' +
                    '<td class="num">' + (x.prior_ratio !== null && x.prior_ratio !== undefined ?
                      Ui.pct(x.prior_ratio) : '<span title="이전 구간 표본 부족">표본 부족</span>') + '</td>' +
                    '<td class="num">' + (x.delta !== null && x.delta !== undefined ?
                      ((x.delta > 0 ? '+' : '') + Ui.pct(x.delta)) : '-') + '</td>' +
                    '<td class="num">' + x.n_recent + '</td>');
                  return tr;
                }));
            }
            if (s.divisional) {
              head('⑥ 분할·계속출원 타이밍');
              addFig(s.divisional.fig,
                'X축=분할출원일, 레인=기업, ◇=분할출원 1건. 읽는 법: 분할출원이 단기간에 몰린 ' +
                '구간(아래 버스트 표)은 방어적 청구항 조정이 있었을 가능성이 있는 시기입니다. ' +
                Ui.esc(s.divisional.note || ''));
              addTable(['기업', '집중 구간', '건수', ''],
                (s.divisional.bursts || []).map(function (x) {
                  var tr = document.createElement('tr');
                  tr.insertAdjacentHTML('beforeend',
                    '<td>' + Ui.esc(x.company) + '</td>' +
                    '<td>' + Ui.esc(x.start) + ' ~ ' + Ui.esc(x.end) + '</td>' +
                    '<td class="num">' + x.n + '</td>');
                  var td = document.createElement('td');
                  td.appendChild(drillCell('특허 보기', x.drill));
                  tr.appendChild(td);
                  return tr;
                }));
            }
            if (s.anomaly) {
              head('⑦ 심사 소요기간 이상탐지 (' + Ui.esc(s.anomaly.start_basis) + ' 기준)');
              addFig(s.anomaly.fig,
                '바이올린=기술분류별 심사 소요기간 분포. 읽는 법: 분포에서 크게 벗어난 특허(아래 ' +
                '목록)가 이상치입니다. 비정상적으로 길게 심사받고도 등록된 특허는 심사 저항을 견딘 ' +
                '강한 권리 후보, 비정상적으로 짧으면 명확한 신기술이거나 우선심사입니다.');
              addTable(['특허', '기술분류', '소요(개월)', 'z', '유형', 'OA 횟수', '출원인'],
                (s.anomaly.outliers || []).map(function (x) {
                  var tr = document.createElement('tr');
                  var td0 = document.createElement('td');
                  td0.appendChild(drillCell(x.id, x.drill));
                  tr.appendChild(td0);
                  tr.insertAdjacentHTML('beforeend',
                    '<td>' + Ui.esc(x.tech) + '</td>' +
                    '<td class="num">' + x.months + '</td>' +
                    '<td class="num">' + x.z + '</td>' +
                    '<td>' + Ui.esc(x.kind) + '</td>' +
                    '<td class="num">' + (x.oa !== null && x.oa !== undefined ? x.oa : '-') + '</td>' +
                    '<td>' + Ui.esc(x.applicant) + '</td>');
                  return tr;
                }));
            }
            if (s.disclosure) {
              head('⑧ 개시 충실도 — 도면 수·명세서 분량 (상대비교 전용)');
              addFig(s.disclosure.fig,
                '행=기업, 열=기술분류, 색=분류 내 평균 도면 수 z-score(초록=분류 평균보다 충실, ' +
                '빨강=부실). 읽는 법: 출원량은 많은데 개시 충실도가 낮은 기업은 방어적 양적 출원 ' +
                '성향, 높은 기업은 실제 개발이 진행됐을 가능성이 큽니다. ' +
                Ui.esc(s.disclosure.note || ''));
              addFig(s.disclosure.fig_scatter, null);
            }
            if (s.trial) {
              head('⑨ 심판·소송 충돌 지도 — 분쟁 기록은 가치의 직접 증거');
              addFig(s.trial.fig,
                'X축=심판 건수, Y축=기술분류. 읽는 법: 심판이 집중된 분류가 곧 상업적으로 가장 ' +
                '뜨거운 영역입니다 (hover 에 분류 내 심판 비율).');
              if (s.trial.network) {
                var cyH = Ui.el('<div class="cy-holder"></div>');
                c.body.appendChild(cyH);
                Render.cytoscape(cyH, s.trial.network, {});
                c.body.appendChild(chartCap('화살표=심판 청구 방향(청구인→권리자), 두께=건수, ' +
                  '엣지 색=주요 기술분류, 빨간 노드=심판을 가장 많이 받은 기업. 읽는 법: 화살표가 ' +
                  '한 기업으로 수렴하면 그 기업이 병목(핵심) 특허 보유자입니다. 노드 클릭 시 해당 ' +
                  '기업 특허가 열립니다.'));
              }
              addFig(s.trial.fig_court,
                'X축=건수, Y축=관할 법원. 읽는 법: 특허법원·대법원 단계까지 간 분쟁이 많을수록 ' +
                '끝까지 다투는 고가치 권리이며, 지방법원 위주면 침해금지·손해배상 소송 무대입니다.');
              if ((s.trial.hot_patents || []).length) {
                c.body.appendChild(Ui.el('<div style="font-weight:700;font-size:12.5px;margin:8px 0 4px">' +
                  '🔥 다분쟁 특허 (심판+소송 횟수 상위 — 상업적으로 가장 뜨거운 권리)</div>'));
                addTable(['특허', '명칭', '권리자/출원인', '심판', '소송', '관할법원', '피인용'],
                  s.trial.hot_patents.map(function (x) {
                    var tr = document.createElement('tr');
                    var td0 = document.createElement('td');
                    td0.appendChild(drillCell(x.id, x.drill));
                    tr.appendChild(td0);
                    tr.insertAdjacentHTML('beforeend',
                      '<td>' + Ui.esc(x.title) + '</td><td>' + Ui.esc(x.applicant) + '</td>' +
                      '<td class="num">' + x.trials + '</td><td class="num">' + x.lawsuits + '</td>' +
                      '<td>' + Ui.esc(x.court || '-') + '</td>' +
                      '<td class="num">' + (x.cites !== null && x.cites !== undefined ? x.cites : '-') + '</td>');
                    return tr;
                  }));
              }
              if (s.trial.dispute_quality) {
                c.body.appendChild(Ui.el('<div style="margin-top:6px;color:#46607a;font-size:12px">' +
                  '분쟁 특허 평균 피인용 <b>' + Ui.num(s.trial.dispute_quality.disputed_avg, 1) +
                  '</b> vs 일반 특허 <b>' + Ui.num(s.trial.dispute_quality.normal_avg, 1) +
                  '</b> — 분쟁 대상이 곧 핵심 기술이라는 신호입니다.</div>'));
              }
              if ((s.trial.trial_types || []).length) {
                c.body.appendChild(Ui.el('<div style="margin-top:6px">' +
                  s.trial.trial_types.map(function (t) {
                    return '<span class="badge">' + Ui.esc(t.type) + ' ' + t.n + '건</span>';
                  }).join('') + '</div>'));
              }
            }
            if (s.gov_program) {
              head('⑩ 국가연구 과제 연계 — 정부 R&D 가 만드는 특허');
              c.body.appendChild(Ui.el('<div style="color:#46607a;font-size:12.5px;margin-bottom:6px">' +
                '전체의 <b>' + Ui.pct(s.gov_program.linked_ratio) + '</b> (' +
                Ui.num(s.gov_program.n_linked, 0) + '건)가 국가연구 과제 연계 특허' +
                (s.gov_program.quality ? ' · 평균 피인용: 과제 연계 <b>' +
                  Ui.num(s.gov_program.quality.gov_avg, 1) + '</b> vs 자체 <b>' +
                  Ui.num(s.gov_program.quality.own_avg, 1) + '</b>' : '') + '</div>'));
              addFig(s.gov_program.fig_prog,
                'X축=특허 수, Y축=국가연구 과제명. 읽는 법: 특허 산출이 많은 국책과제가 이 분야 ' +
                'R&D 의 실질적 자금줄입니다 — 과제 종료 시점이 출원 흐름 변곡점이 될 수 있습니다.');
              addFig(s.gov_program.fig_company,
                'X축=국가과제 연계율, Y축=기업. 읽는 법: 연계율이 높은 기업은 정부 R&D 의존형 — ' +
                '정책·과제 선정 변화에 출원이 민감합니다. 낮은 기업은 자체 자금 R&D 중심입니다.');
              addFig(s.gov_program.fig_tech,
                'X축=연계율, Y축=기술분류. 읽는 법: 연계율 높은 기술=국가가 전략적으로 밀고 있는 ' +
                '영역 — 정부 로드맵과 함께 읽으면 향후 지원 지속 여부를 가늠할 수 있습니다.');
              if (s.gov_program.note) {
                c.body.appendChild(Ui.el('<div class="disclaimer">' + Ui.esc(s.gov_program.note) + '</div>'));
              }
            }
            if ((r.skipped || []).length) {
              c.body.appendChild(Ui.el('<div class="disclaimer" style="margin-top:12px">생략된 섹션: ' +
                r.skipped.map(function (x) {
                  return Ui.esc(x.section) + ' (' + Ui.esc(x.reason) + ')';
                }).join(' · ') + ' — Settings → 컬럼 매핑에서 해당 WIPS 필드를 매핑하면 활성화됩니다.</div>'));
            }
    }

  /* ---------- 2. 전체 동향 — 포트폴리오 전체의 기본 현황 ---------- */
  Views.basic = function (content) {
    makeTabs(content, [
      { label: '출원 동향', render: statsTab('연도별 출원 동향 (WIPS형 기본 통계 · 출원인 선택 가능)',
          '연도별 전체 출원·등록·유효 건수 추이입니다. 연도는 출원일(없으면 우선일/공개일) 기준이며, 점을 클릭하면 해당 연도의 근거 특허 목록이 열립니다. 상단에서 출원인을 선택하면 그 회사의 출원 동향만 표시됩니다 (공동출원 건 포함).',
          ['annual'],
          'X축=연도(출원일 기준), Y축=특허 건수. 세 선의 간격이 정보입니다: 전체와 등록의 차이=미등록(심사중·거절·포기), 등록과 유효의 차이=소멸된 권리. 읽는 법: 우상향이면 투자 확대 국면이고, 최근 1~2년은 아직 공개되지 않은 출원 때문에 실제보다 낮게 보일 수 있으므로 하락으로 단정하지 마세요. 출원인을 선택하면 공동출원 건을 포함한 그 회사 기준 추이입니다.', true) },
      { label: '국가·출원인', render: statsTab('국가별 분포 · 출원인 순위 · 연도별 버블 · 활동 매트릭스',
          '국가별 출원 분포, 출원인 순위 Top, 출원인×출원연도 버블(크기=출원건수), 출원인×연도 활동 매트릭스(진할수록 활발)입니다. 막대·버블을 클릭하면 해당 국가/출원인(해당 연도)의 특허 목록이 열립니다. 공동출원 특허는 Settings → 분석 설정의 "공동출원 집계" 방식(기본: 각 공동출원인에게 1건씩)을 따라 집계됩니다.',
          ['country', 'applicants', 'applicant_year_bubble', 'applicant_year'],
          '국가별 분포: X축=국가, Y축=건수 — 어느 시장에 권리를 확보했는지 보여줍니다. 출원인 순위: X축=건수, Y축=출원인 — 이 분야의 주요 플레이어 순위입니다. 출원인×출원연도 버블: X축=출원연도(1년=1칸), Y축=출원인(위가 누적 1위), 버블 크기·색=그 해 출원건수 — 큰 버블이 이어지는 줄=꾸준한 투자 기업, 최근에만 큰 버블이 생긴 기업=신규 집중 투자, 버블이 사라진 기업=투자 축소 신호이며 버블 클릭 시 그 기업·연도 특허가 열립니다. 활동 매트릭스: 같은 데이터의 히트맵 보기입니다.') },
      { label: '심화 분석', render: function (h) {
        analysisCard({
          analysis: 'advanced-stats', holder: h,
          title: '심화 통계 (심사기간 · 만료 타임라인 · 청구항 · 공동출원 · IPC)',
          help: '윈텔립스/WIPS Excel 의 서지 컬럼(등록일·만료예정일·청구항 수·공동출원인·IPC)으로 도출하는 심화 인사이트입니다. 필요한 컬럼이 없는 섹션은 자동으로 생략되고 하단에 사유가 표시됩니다.',
          renderOk: function (r, c, setTarget) {
            var s = r.sections || {};
            var first = true;
            function addFig(fig, capText, tall) {
              if (!fig) return;
              var holder = Ui.el('<div class="chart-holder"' +
                (tall ? ' style="min-height:460px"' : '') + '></div>');
              c.body.appendChild(holder);
              Render.plotly(holder, fig, plotlyDrill);
              if (first) { setTarget({ kind: 'plotly', el: holder }); first = false; }
              if (capText) c.body.appendChild(chartCap(capText));
            }
            if (s.prosecution) {
              addFig(s.prosecution.fig_year,
                'X축=출원연도, Y축=출원부터 등록까지 평균 소요기간(개월). 읽는 법: 기간이 ' +
                '길어지는 추세면 심사 적체 또는 권리화 난이도 상승을, 짧아지면 우선심사 활용 ' +
                '등을 시사합니다. 최근 연도는 아직 등록이 완료되지 않은 건이 빠져 짧게 보일 수 ' +
                '있습니다.');
              addFig(s.prosecution.fig_company,
                'X축=평균 등록 소요기간(개월), Y축=기업. 읽는 법: 기간이 짧은 기업은 우선심사 ' +
                '등 빠른 권리화 전략을, 긴 기업은 심사 대응이 길거나 분할·보정을 많이 거치는 ' +
                '경향을 시사합니다. 막대 클릭 시 해당 기업 특허 목록이 열립니다.');
            }
            if (s.expiry) {
              addFig(s.expiry.fig,
                'X축=만료 연도, Y축=만료 예정 건수(' + Ui.esc(s.expiry.scope || '') + ' 기준). ' +
                '읽는 법: 만료가 몰린 해(특허 절벽) 이후에는 해당 기술의 설계 자유도가 커집니다. ' +
                '경쟁사 핵심특허의 만료 시점은 진입 타이밍 신호가 됩니다.');
              if ((s.expiry.expiring || []).length) {
                var rows = s.expiry.expiring.map(function (x) {
                  var tr = document.createElement('tr');
                  var td0 = document.createElement('td');
                  td0.appendChild(drillCell(x.id, x.drill));
                  tr.appendChild(td0);
                  tr.insertAdjacentHTML('beforeend', '<td>' + Ui.esc(x.title) + '</td><td>' +
                    Ui.esc(x.applicant) + '</td><td>' + Ui.esc(x.expiry) + '</td>' +
                    '<td class="num">' + (x.cites !== null ? x.cites : '-') + '</td>');
                  return tr;
                });
                var tbl = Ui.el(simpleTable(['번호', '명칭', '출원인', '만료일', '피인용'], []));
                rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
                c.body.appendChild(Ui.el('<div style="margin-top:6px"><b style="font-size:12px">' +
                  '3년 내 만료 예정 주요 특허 (피인용 상위)</b></div>'));
                c.body.appendChild(tbl);
              }
            }
            if (s.claims) {
              addFig(s.claims.fig_company,
                'X축=평균 청구항 수, Y축=기업. 읽는 법: 청구항 수는 권리 설계의 정교함·범위의 ' +
                '프록시입니다. 평균이 높은 기업은 회피설계를 어렵게 만드는 촘촘한 권리망을 ' +
                '구축하는 경향이 있습니다 (hover 에 독립항 수 병기).');
              addFig(s.claims.fig_relation,
                'X축=청구항 수 구간, Y축=평균 피인용. 읽는 법: 구간이 올라갈수록 피인용이 ' +
                '높아지면 이 분야에서는 정교한 권리 설계와 기술 영향력이 함께 가는 것입니다.');
            }
            if (s.coapplicant) {
              var cyHolder = Ui.el('<div class="cy-holder"></div>');
              c.body.appendChild(cyHolder);
              Render.cytoscape(cyHolder, s.coapplicant.network, {});
              c.body.appendChild(chartCap('노드=기업(크기=공동출원 참여 건수), 선=두 기업의 ' +
                '공동출원 건수(두께=빈도). 읽는 법: 굵게 연결된 기업쌍은 공동 R&D·산학협력 등 ' +
                '긴밀한 협력 관계입니다. 경쟁사가 누구와 협력하는지로 공급망·기술 제휴 구도를 ' +
                '읽을 수 있습니다. 노드 클릭 시 해당 기업 특허가 열립니다.'));
            }
            if (s.ipc) {
              addFig(s.ipc.fig,
                'X축=건수, Y축=IPC/CPC 서브클래스(4자리, 예: H01L=반도체 장치). 읽는 법: ' +
                '당사 기술분류 체계와 별개인 국제 표준 분류 관점의 분포로, 내부 분류가 놓친 ' +
                '인접 기술 영역을 확인할 수 있습니다.');
            }
            if ((r.skipped || []).length) {
              c.body.appendChild(Ui.el('<div class="disclaimer">생략된 섹션: ' +
                r.skipped.map(function (x) {
                  return Ui.esc(x.section) + '(' + Ui.esc(x.reason) + ')';
                }).join(', ') + '</div>'));
            }
          }
        });
      } }
    ]);
  };

  /* ---------- 2.5 심층 시그널 — 잘 안 쓰는 필드 기반 신호 6종 ---------- */
  Views.deepsig = function (content) {
    makeTabs(content, [
      deepTab('시그널: 수명·시장', ['survival', 'market_entry'],
        '심층 시그널 — 연차료 생존곡선 · 지정국 진입 순서',
        '연차료 소멸 기록으로 "기업 스스로 매긴 특허 가치"(생존곡선)를, 패밀리 지정국 진입 ' +
        '시차로 시장 베팅 순서를 읽습니다.'),
      deepTab('시그널: 심사 이력', ['examiner_eye', 'expedited', 'anomaly'],
        '심층 시그널 — 심사관 인용 · 우선심사 · 심사기간 이상탐지',
        '심사관(OA) 인용 vs 출원인측 인용 격차로 무효 리스크 후보 영역을, 우선심사 비율 급등으로 ' +
        '사업화 임박 신호를, 심사 소요기간 이상치로 강한 권리 후보를 찾습니다.'),
      deepTab('시그널: 출원 행태', ['agent', 'divisional', 'disclosure'],
        '심층 시그널 — 대리인 전환 · 분할출원 · 개시 충실도',
        '대리인 교체 시점(상관 신호), 분할출원 집중 구간(방어적 청구항 조정 가능성), ' +
        '도면 수 기반 개시 충실도(기업 내 상대비교 전용)를 봅니다.'),
      deepTab('시그널: 분쟁·국가과제', ['trial', 'gov_program'],
        '심층 시그널 — 심판·소송 충돌 지도 · 국가연구 과제 연계',
        '심판·소송 기록으로 상업적으로 가장 뜨거운 기술·특허를, 국가연구 과제명으로 정부 R&D 가 ' +
        '만드는 특허 지형을 봅니다. 국가과제 막대를 클릭하면 해당 과제의 특허 목록이 열리고 ' +
        'Excel 로 내려받을 수 있습니다.'),
      deepPlusTab('시그널: 라이선스·표준·양도', ['license', 'sep', 'assignment'],
        '특수 신호 — 실시권(라이선스) · 표준특허 · 권리변동 타임라인',
        '실시권 설정(=기술료 수익화의 직접 증거), 표준화기구 선언 특허(SEP), 최근 양도 기록' +
        '(누가 언제 어떤 유형으로 특허를 거래했나)을 봅니다.'),
      deepPlusTab('시그널: 거절·과학·심사관', ['rejection', 'science', 'examiner'],
        '특수 신호 — 거절 사유 · 과학 연계성 · 심사관',
        '거절 사유 유형 분포와 기업별 거절결정률(출원 전략 개선 지점), 비특허문헌(논문) 인용 기반 ' +
        '과학 연계성(기초연구 근접도), 심사관별 처리 현황(개인 실명 — 내부 참고용)을 봅니다.')
    ]);
  };


  /* ---------- 3. 기술 분석 (Technology) ---------- */
  Views.evolution = function (content) {
    makeTabs(content, [
      { label: '기술분류 동향', render: statsTab('기술분류별 건수 · 연도 동향 (출원인 선택 가능)',
          '기술분류별 누적 건수 순위와 분류×연도 동향 매트릭스입니다. 상단에서 출원인을 선택하면 그 회사의 기술 포트폴리오만 표시됩니다. 다중분류는 Settings 의 처리방식을 따르지 않고 각 분류에 1건씩 계산합니다.',
          ['tech', 'tech_year'],
          '순위: X축=건수, Y축=기술분류 — 포트폴리오가 집중된 기술. 동향 매트릭스: X축=연도, Y축=기술분류, 색=그 해 건수. 읽는 법: 오른쪽(최근)으로 갈수록 진해지는 분류=성장 기술, 왼쪽만 진하고 최근이 옅은 분류=쇠퇴 기술입니다. 출원인을 선택하면 그 회사 기준으로 같은 해석을 적용하세요.', true) },
      { label: '기술분류 트리', render: function (h) {
        analysisCard({
          analysis: 'tech-tree', holder: h,
          title: '기술분류 트리맵 — 대·중·소 계층 (출원인 선택 가능)',
          controls: companySelectControls('출원인 선택'),
          help: '대분류>중분류>소분류 계층을 면적=문헌 수인 트리맵으로 봅니다. ' +
            '각 문헌의 레벨별 대표(첫) 분류로 경로를 만들며, 하위 분류가 없는 문헌은 ' +
            '있는 레벨까지만 집계됩니다. 상단에서 출원인을 선택하면 그 회사(공동출원 ' +
            '포함) 포트폴리오의 트리가 됩니다.',
          guide: '색=대분류(하위로 갈수록 연해짐), 면적=문헌 수. 읽는 법: 큰 칸=포트폴리오가 ' +
            '집중된 기술, 부모 칸의 남는 여백=하위 분류 미기재 문헌입니다. 하위가 있는 칸을 ' +
            '클릭하면 그 분류로 확대되고(상단 경로 바로 복귀), 최하위 칸을 클릭하면 근거 특허 ' +
            '목록이 열립니다. 대/중/소 컬럼이 일부만 매핑된 경우 있는 레벨까지만 그려집니다.',
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="chart-holder tall"></div>');
            c.body.appendChild(holder);
            Render.plotly(holder, r.figure, function (drill, cd) {
              if (cd && cd.leaf === false) return; // 상위 칸 클릭=확대만
              plotlyDrill(drill);
            });
            setTarget({ kind: 'plotly', el: holder });
          }
        });
      } },
      { label: '기술×연도 버블', render: function (h) {
        var sel1, sel2, sel3, lvlSel;
        function selectedCompanies() {
          return [sel1.value, sel2.value, sel3.value].filter(function (v) { return v; });
        }
        analysisCard({
          analysis: 'tech-year-bubble', holder: h,
          title: '기술분류 × 출원연도 버블 (대·중·소 선택 · 출원인 최대 3개사 비교)',
          help: 'X축=출원연도(1년=1칸), Y축=기술분류, 버블 크기=해당 연도·분류의 출원건수입니다. ' +
            '상단에서 출원인을 선택하면 그 회사만 표시되고, 2~3개사를 고르면 회사별 색으로 같은 축에 ' +
            '겹쳐 비교합니다 (같은 기술 행에서 세로로 살짝 어긋나게 배치되어 겹침 없이 비교 가능). ' +
            '분류 선택에서 "대›중›소 계층"을 고르면 Y축이 대분류 › 중분류 › 소분류 경로로 표시되어 ' +
            '어느 소분류가 어느 상위 분류에 속하는지 한눈에 보입니다 (같은 대분류끼리 묶여 정렬). ' +
            '아무도 선택하지 않으면 전체 데이터 기준입니다. 집계 기준: 전체 보기는 특허 1건=1번 ' +
            '집계로 공동출원이어도 중복 계산되지 않습니다. 회사를 선택하면 공동출원 건이 그 회사 ' +
            '것으로 포함되며, 공동출원 관계인 두 회사를 함께 선택한 경우에만 같은 특허가 양쪽 ' +
            '시리즈에 나타납니다.',
          guide: '읽는 법(단일/전체): 오른쪽으로 갈수록 최근이며, 행에서 버블이 커지는 기술=투자 확대, ' +
            '사라지는 기술=철수 신호입니다. 읽는 법(비교): 같은 기술 행에서 색이 다른 버블의 등장 ' +
            '시점을 비교하면 누가 먼저 진입했는지(선행), 크기를 비교하면 누가 더 크게 투자하는지 ' +
            '보입니다. 한 회사에만 버블이 있는 행=그 회사의 독점 영역이자 상대 회사의 공백입니다. ' +
            '버블 클릭 시 해당 (회사×)기술×연도 특허가 열립니다.',
          controls: function (c, reload) {
            function go() {
              reload({ companies: selectedCompanies(), level: lvlSel.value || null });
            }
            function mkSel(ph) {
              var s = Ui.el('<select><option value="">' + ph + '</option></select>');
              ((State.filterOptions || {}).applicants || []).slice(0, 300).forEach(function (a) {
                var o = document.createElement('option'); o.value = a; o.textContent = a;
                s.appendChild(o);
              });
              s.addEventListener('change', go);
              return s;
            }
            lvlSel = Ui.el('<select><option value="">분류: 통합</option>' +
              '<option value="l1">분류: 대</option><option value="l2">분류: 중</option>' +
              '<option value="l3">분류: 소</option>' +
              '<option value="path">분류: 대›중›소 계층</option></select>');
            lvlSel.addEventListener('change', go);
            sel1 = mkSel('회사 1 (전체)'); sel2 = mkSel('회사 2'); sel3 = mkSel('회사 3');
            c.controls.prepend(sel3); c.controls.prepend(sel2); c.controls.prepend(sel1);
            c.controls.prepend(lvlSel);
          },
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="chart-holder tall"></div>');
            c.body.appendChild(holder);
            Render.plotly(holder, r.figure, plotlyDrill);
            setTarget({ kind: 'plotly', el: holder });
          }
        });
      } },
      { label: '기술 생애주기', render: function (h) {
        analysisCard({
          analysis: 'lifecycle', holder: h, title: '기술 생애주기 Phase Map (출원인 선택 가능)',
          controls: companySelectControls('출원인 선택'),
          help: 'X=성숙도(경과연수·누적건수 정규화), Y=모멘텀(성장률·신규출원인 정규화). 단계: Emerging/Growing/Competitive/Mature/Declining/Re-emerging. 화살표=전년 대비 이동. 출원인을 선택하면 그 회사(공동출원 포함) 문헌 기준으로 재계산되며, 이때 경쟁 강도(출원인 수) 색은 의미가 없어 단일 색으로 표시됩니다.',
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="chart-holder"></div>');
            c.body.appendChild(holder);
            Render.plotly(holder, r.figure, plotlyDrill);
            setTarget({ kind: 'plotly', el: holder });
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
            ((State.filterOptions || {}).applicants || []).slice(0, 300).forEach(function (a) {
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
      } },
      { label: '분류축 교차 (A·B·C)', render: function (h) {
        analysisCard({
          analysis: 'axis-cross', holder: h,
          title: '기술분류 A·B·C축 교차 해석',
          help: 'A축(기존 기술 대/중/소분류)과 별도 관점의 B축·C축 분류(예: 응용처, 재료/공정)를 ' +
            '교차해 봅니다. Settings → 컬럼 매핑에서 "B축 대/중/소분류", "C축 대/중/소분류"를 ' +
            '매핑하면 활성화되며, 매핑된 축의 실제 데이터만 사용합니다 (없는 축은 자동 제외, 값 추정 없음).',
          guide: '교차 매트릭스: 행·열=두 축의 분류(각 축은 매핑된 가장 세밀한 레벨, 소→중→대 우선), ' +
            '셀=두 값을 동시에 가진 특허 수. 읽는 법: 진한 셀=두 관점이 만나는 핵심 영역(예: ' +
            '"하이브리드 본딩 × 차량"), 행·열은 활발한데 셀이 0인 곳=한 관점에서는 다루면서 다른 ' +
            '관점과 결합되지 않은 공백 후보. 셀 클릭 시 해당 교차 특허가 열립니다. ' +
            'Sunburst(3축 모두 매핑 시): 안쪽 고리=A축, 중간=B축, 바깥=C축 — 특정 기술이 어떤 ' +
            '응용·재료로 분해되는지 계층으로 보여줍니다.',
          renderOk: function (r, c, setTarget) {
            var first = true;
            (r.pairs || []).forEach(function (p) {
              var holder = Ui.el('<div class="chart-holder"></div>');
              c.body.appendChild(holder);
              Render.plotly(holder, p.figure, plotlyDrill);
              if (first) { setTarget({ kind: 'plotly', el: holder }); first = false; }
              c.body.appendChild(chartCap(p.pair + ': 최다 교차 "' +
                Ui.esc(p.top_cell.a) + ' × ' + Ui.esc(p.top_cell.b) + '" ' +
                Ui.num(p.top_cell.n, 0) + '건 · 공백 셀 ' + Ui.pct(p.zero_ratio) +
                (p.avg_spread !== null && p.avg_spread !== undefined ?
                  ' · 행별 분산도(엔트로피) ' + Ui.num(p.avg_spread, 2) +
                  ' (낮을수록 두 분류가 연동)' : '')));
            });
            if (r.sunburst) {
              var sh = Ui.el('<div class="chart-holder tall"></div>');
              c.body.appendChild(sh);
              Render.plotly(sh, r.sunburst);
            }
          }
        });
      } },
      { label: '신흥 기술 탐지 (임베딩)', render: function (h) {
        analysisCard({
          analysis: 'emerging-clusters', holder: h,
          title: '신흥 기술 조기 탐지 — Emerging Cluster Detection (출원인·기간 선택 가능)',
          controls: function (c, reload) {
            var cur = { company: null, recent_years: null };
            var ySel = Ui.el('<select><option value="">최근 3년 기준</option>' +
              '<option value="2">최근 2년</option><option value="4">최근 4년</option>' +
              '<option value="5">최근 5년</option></select>');
            ySel.addEventListener('change', function () {
              cur.recent_years = ySel.value ? parseInt(ySel.value, 10) : null;
              reload(cur);
            });
            var sel = Ui.el('<select><option value="">전체 출원인</option></select>');
            ((State.filterOptions || {}).applicants || []).slice(0, 300).forEach(function (a) {
              var o = document.createElement('option'); o.value = a; o.textContent = a;
              sel.appendChild(o);
            });
            sel.addEventListener('change', function () {
              cur.company = sel.value || null;
              reload(cur);
            });
            c.controls.prepend(ySel);
            c.controls.prepend(sel);
            c.controls.prepend(Ui.el('<span style="font-size:11.5px;color:#647b8d">' +
              '출원인·Y축 기간</span>'));
          },
          help: '전체 문헌 텍스트(요약·독립청구항)를 KR-SBERT 임베딩으로 군집화한 뒤 각 군집의 ' +
            '출원 시점 분포를 봅니다. 최근 3년에 몰려 있고, 신규 출원인이 늘고, 이전에 없던 ' +
            '새 군집이면 신흥 기술 후보입니다. 군집 라벨은 중심에 가까운 특허들의 특징 키워드로 ' +
            '자동 생성됩니다.',
          guide: 'X축=군집 평균 출원연도(오른쪽=최근 기술), Y축=최근 3년 출원 비중(위=신흥), ' +
            '버블 크기=군집 특허 수, 색=신규 출원인 비율(진할수록 새 플레이어 유입), ' +
            '빨간 테두리=이전 기간에 없던 새 군집. 읽는 법: 우상단의 진한 버블이 가장 강한 ' +
            '신흥 신호입니다. 버블 클릭 시 군집 소속 특허가 열립니다. 군집·라벨은 임베딩 기반 ' +
            '자동 산출로, 기술 가치 판단이 아닌 조기 탐지 신호입니다.',
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="chart-holder tall"></div>');
            c.body.appendChild(holder);
            Render.plotly(holder, r.figure, plotlyDrill);
            setTarget({ kind: 'plotly', el: holder });
            var rows = (r.clusters || []).map(function (x) {
              var tr = document.createElement('tr');
              var td0 = document.createElement('td');
              td0.appendChild(drillCell(x.label, x.drill));
              if (x.label_source === 'llm' && (x.keywords || []).length) {
                td0.appendChild(Ui.el('<br><span style="color:#93a5b4;font-size:10.5px">키워드: ' +
                  Ui.esc(x.keywords.slice(0, 3).join(', ')) + '</span>'));
              }
              tr.appendChild(td0);
              tr.insertAdjacentHTML('beforeend',
                '<td>' + (x.rep_titles || []).map(function (t) {
                  return '<div style="font-size:11px;color:#46607a">· ' + Ui.esc(t) + '</div>';
                }).join('') + '</td>' +
                '<td>' + (x.emerging ? '<span class="badge good">신흥 후보</span>' : '') +
                (x.is_new_cluster ? ' <span class="badge warn">새 군집</span>' : '') + '</td>' +
                '<td class="num">' + Ui.num(x.n, 0) + '</td>' +
                '<td class="num">' + x.first_year + '</td>' +
                '<td class="num">' + Ui.pct(x.recent_share) + '</td>' +
                '<td class="num">' + (x.new_applicant_ratio !== null && x.new_applicant_ratio !== undefined ?
                  Ui.pct(x.new_applicant_ratio) : '-') + '</td>' +
                '<td class="num">' + Ui.num(x.score, 2) + '</td>' +
                '<td>' + (x.top_applicants || []).map(function (a) {
                  return '<span class="badge">' + Ui.esc(a.name) + ' ' + a.count + '</span>';
                }).join('') + '</td>');
              return tr;
            });
            var tbl = Ui.el(simpleTable(
              ['군집 명칭', '대표 특허 (중심 최근접)', '판정', '건수', '최초 출원', '최근 3년 비중', '신규 출원인', '점수', '주요 출원인'], []));
            rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
            var wrap = Ui.el('<div style="overflow-x:auto;max-height:320px;overflow-y:auto;margin-top:8px"></div>');
            wrap.appendChild(tbl);
            c.body.appendChild(wrap);
            if (r.methods) {
              c.body.appendChild(Ui.el('<div style="margin-top:6px;color:#647b8d;font-size:11.5px">방법: 임베딩 ' +
                Ui.esc(r.methods.embedding) + ' · 텍스트 ' + Ui.esc(r.methods.text_source) +
                ' · 문헌 ' + Ui.num(r.methods.n_docs, 0) + '건 · 군집 명칭 ' +
                (r.methods.labeling === 'llm' ? 'LLM 생성 (키워드·대표 특허명 근거)' :
                  '특징 키워드 자동 — Settings 에서 LLM 인사이트를 켜면 읽기 쉬운 기술 명칭으로 자동 생성') +
                '</div>'));
            }
          }
        });
      } }
    ]);
  };

  /* ---------- 3. Competitor Intelligence ---------- */
  Views.competitor = function (content) {
    makeTabs(content, [
      { label: '출원인 포커스', render: function (h) {
        analysisCard({
          analysis: 'company-focus', holder: h,
          title: '출원인 포커스 — 집중 기술 · 신규 진입 · 급부상 (출원인 선택 필수)',
          controls: companySelectControls('출원인 선택'),
          help: '한 회사를 골라 ① 어떤 기술에 집중하는지(주력), ② 최근 몇 년 안에 처음 ' +
            '진입한 신규 기술이 무엇인지(🆕 초록), ③ 누적은 작지만 최근 출원이 몰리는 ' +
            '급부상 아이템(★ 빨강)이 무엇인지 봅니다. 공동출원 건도 그 회사 것으로 포함됩니다.',
          guide: '포커스 맵: X축=누적 출원 건수(로그축, 오른쪽=주력 기술), Y축=최근 3년 출원 ' +
            '비중(위=최근에 몰림). 초록 버블(🆕)=신규 진입 — 그 회사의 해당 분류 최초 출원이 ' +
            '최근 3년 안 (그 전엔 0건). 빨간 버블(★)=급부상 후보 — 최근 3년 2건 이상, ' +
            '출원의 절반 이상이 최근 3년, 직전 3년보다 증가, 누적은 회사 중앙값 이하. ' +
            '초록 버블에 빨간 테두리 = 신규 진입이면서 급부상(가장 강한 신호). 화면에 ' +
            '명시된 규칙만 사용하며, 버블·막대 클릭 시 그 회사의 해당 분류 특허가 열립니다.',
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="chart-holder tall"></div>');
            c.body.appendChild(holder);
            Render.plotly(holder, r.figure, plotlyDrill);
            setTarget({ kind: 'plotly', el: holder });
            var h2 = Ui.el('<div class="chart-holder"></div>');
            c.body.appendChild(h2);
            Render.plotly(h2, r.fig_top, plotlyDrill);
            var ry = r.recent_years || 3;
            // 🆕 신규 진입 기술 (최근 N년 내 첫 출원 — 회사가 새로 여는 영역)
            var newRows = (r.new_entries || []).map(function (x) {
              var tr = document.createElement('tr');
              var td0 = document.createElement('td');
              td0.appendChild(drillCell(x.tech, x.drill));
              tr.appendChild(td0);
              tr.insertAdjacentHTML('beforeend',
                '<td class="num">' + (x.first_year || '-') + '</td>' +
                '<td class="num">' + Ui.num(x.total, 0) + '</td>' +
                '<td class="num">' + Ui.num(x.recent, 0) + '</td>' +
                '<td class="num">' + Ui.num(x.market_total, 0) + '</td>' +
                '<td class="num">' + Ui.pct(x.market_share) + '</td>' +
                '<td>' + (x.rising ? '<span class="badge warn">★ 급부상 동시</span>' : '') +
                '</td>');
              return tr;
            });
            if (newRows.length) {
              c.body.appendChild(Ui.el('<div style="font-weight:700;font-size:13px;' +
                'margin:12px 0 4px;color:#1e7a45">🆕 신규 진입 기술 (' + newRows.length +
                '개 — 최근 ' + ry + '년 내 첫 출원, 그 전엔 0건)</div>'));
              var ntbl = Ui.el(simpleTable(
                ['기술분류', '최초 출원', '누적', '최근 ' + ry + '년', '시장 전체',
                 '시장 점유', '신호'], []));
              newRows.forEach(function (tr) { ntbl.querySelector('tbody').appendChild(tr); });
              var nwrap = Ui.el('<div style="overflow-x:auto;max-height:280px;overflow-y:auto"></div>');
              nwrap.appendChild(ntbl);
              c.body.appendChild(nwrap);
            } else {
              c.body.appendChild(Ui.el('<div style="color:#647b8d;font-size:12px;' +
                'margin:12px 0 4px">🆕 최근 ' + ry + '년 내 처음 진입한 기술분류는 ' +
                '없습니다 — 기존 영역 중심의 포트폴리오입니다.</div>'));
            }
            var rows = (r.rising || []).map(function (x) {
              var tr = document.createElement('tr');
              var td0 = document.createElement('td');
              td0.appendChild(drillCell(x.tech, x.drill));
              tr.appendChild(td0);
              tr.insertAdjacentHTML('beforeend',
                '<td class="num">' + Ui.num(x.total, 0) + '</td>' +
                '<td class="num">' + Ui.num(x.recent, 0) + '</td>' +
                '<td class="num">' + Ui.num(x.prev, 0) + '</td>' +
                '<td class="num">' + Ui.pct(x.recent_share) + '</td>' +
                '<td class="num">' + Ui.num(x.market_total, 0) + '</td>' +
                '<td class="num">' + Ui.pct(x.market_share) + '</td>');
              return tr;
            });
            if (rows.length) {
              c.body.appendChild(Ui.el('<div style="font-weight:700;font-size:13px;' +
                'margin:12px 0 4px;color:#c0392b">★ 급부상 아이템 후보 (' + rows.length + '개)</div>'));
              var tbl = Ui.el(simpleTable(
                ['기술분류', '누적', '최근 ' + ry + '년',
                 '직전 ' + ry + '년', '최근 비중', '시장 전체', '시장 점유'], []));
              rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
              var wrap = Ui.el('<div style="overflow-x:auto;max-height:280px;overflow-y:auto"></div>');
              wrap.appendChild(tbl);
              c.body.appendChild(wrap);
            }
          }
        });
      } },
      { label: '기술 DNA', render: function (h) {
        analysisCard({
          analysis: 'company-dna', holder: h, title: '경쟁사 기술 DNA Fingerprint',
          help: '12개 지표(집중도 HHI/다양성 entropy/신규진입률/조합다양성/패밀리규모/해외범위/등록유지율/평균피인용/후속출원/공동출원/발명자집중도/최근성장률). Hover 에 원값·표준화값 동시 표시.',
          renderOk: function (r, c, setTarget) {
            if (r.definitions) c.body.appendChild(definitionsTable(r.definitions));
            if (r.normalization_note) {
              c.body.appendChild(Ui.el('<div style="color:#647b8d;font-size:11.5px;' +
                'margin:-4px 0 8px">' + Ui.esc(r.normalization_note) + '</div>'));
            }
            var holder = Ui.el('<div class="chart-holder"></div>');
            c.body.appendChild(holder);
            Render.plotly(holder, r.figure);
            setTarget({ kind: 'plotly', el: holder });
            var ph = Ui.el('<div class="chart-holder" style="min-height:300px"></div>');
            c.body.appendChild(ph);
            Render.plotly(ph, r.parcoords);
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
      { label: '권리범위 엔트로피', render: function (h) {
        analysisCard({
          analysis: 'scope-entropy', holder: h,
          title: '권리범위 엔트로피 — 다양성 레이더 · 시계열',
          help: '핵심 질문: "이 회사는 다양한 기술방향을 커버하는가, 같은 청구구조를 반복하는가?" ' +
            '기업별 범주 분포의 정규화 Shannon 엔트로피(0~1)를 기술분류·IPC·청구구조(임베딩 클러스터)·' +
            '청구 카테고리·시장(국가)·키워드 차원에서 계산합니다. 데이터에 없는 차원은 자동 제외됩니다.',
          guide: '레이더: 각 축=다양성 차원, 값=정규화 엔트로피(0=한 범주 반복, 1=전 범주 균등). ' +
            '넓은 다각형=가치사슬을 넓게 커버, 좁은 다각형=특정 구조 반복. ' +
            '시계열: X축=연도, Y축=기술분류 엔트로피 — 상승은 탐색 확대, 하락은 수렴(집중) 신호. ' +
            '막대: 전체 다양성(파랑) vs 핵심 청구구조 집중도 Top-1 비중(빨강) — 건수는 많은데 ' +
            '집중도가 높은 기업은 사실상 동일 조성·구조의 변형 반복일 수 있습니다. ' +
            '해석 규칙: 다양성↑+출원↑=탐색적 R&D 확대 / 다양성↓+출원↑=핵심 상용화 후보 집중 / ' +
            '다양성↑+등록률↓=전략 분산·특허성 검증 부족 가능성 (표 "전략 국면" 열에 자동 판정).',
          renderOk: function (r, c, setTarget) {
            if (r.definitions) c.body.appendChild(definitionsTable(r.definitions, r.official_diff));
            var holder = Ui.el('<div class="chart-holder tall"></div>');
            c.body.appendChild(holder);
            Render.plotly(holder, r.radar);
            setTarget({ kind: 'plotly', el: holder });
            if (r.trend) {
              var th = Ui.el('<div class="chart-holder"></div>');
              c.body.appendChild(th);
              Render.plotly(th, r.trend);
              c.body.appendChild(chartCap('연도별 기술분류 엔트로피: 정점 이후 하락하는 기업은 ' +
                '탐색→수렴 전환 시점을 지난 것으로 추정됩니다 (표본 3건 미만 연도는 생략).'));
            }
            if (r.concentration) {
              var ch = Ui.el('<div class="chart-holder"></div>');
              c.body.appendChild(ch);
              Render.plotly(ch, r.concentration);
            }
            var rows = (r.companies || []).map(function (x) {
              var tr = document.createElement('tr');
              var td0 = document.createElement('td');
              td0.appendChild(drillCell(x.company, x.drill));
              tr.appendChild(td0);
              tr.insertAdjacentHTML('beforeend',
                '<td class="num">' + Ui.num(x.n, 0) + '</td>' +
                '<td class="num">' + Ui.num(x.overall, 2) + '</td>' +
                '<td class="num">' + (x.top1_share !== null && x.top1_share !== undefined ?
                  Ui.pct(x.top1_share) : '-') + '</td>' +
                '<td>' + Ui.esc(x.strategy || '-') + '</td>' +
                '<td class="num">' + (x.transition_year || '-') + '</td>');
              return tr;
            });
            var tbl = Ui.el(simpleTable(
              ['기업', '건수', '전체 다양성', '핵심구조 집중도', '전략 국면 (자동 판정)', '전환 추정연도'], []));
            rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
            var wrap = Ui.el('<div style="overflow-x:auto;margin-top:8px"></div>');
            wrap.appendChild(tbl);
            c.body.appendChild(wrap);
          }
        });
      } },
      { label: '출원인·권리자 관계', render: function (h) {
        analysisCard({
          analysis: 'ownership', holder: h,
          title: '출원인 ↔ 현재 권리자 — 특허 이전(양도) 분석',
          help: '최초 출원인과 현재 권리자가 다른 특허는 양도·매각·M&A 를 거친 특허입니다. ' +
            '누가 누구의 특허를 확보했는지(이전 흐름), 기업별 확보/유출 규모, 거래가 활발한 ' +
            '기술분류, 이전 특허의 품질을 분석합니다. 사명 변경·계열사 재편이 양도처럼 보일 수 ' +
            '있으므로(출원인 표준화로 병합 가능) 통계 신호로 해석하세요.',
          guide: '이전 흐름 네트워크: 화살표=출원인→현재 권리자(특허가 이동한 방향), 두께=건수, ' +
            '노드 색: 초록=순확보(매수 우위)·빨강=순유출(매도 우위)·파랑=균형. 읽는 법: 화살표가 ' +
            '한 기업으로 모이면 그 기업이 적극적 기술 매입자(M&A·포트폴리오 구축)입니다. ' +
            '확보/유출 막대: 오른쪽(초록)=타사 출원 특허를 보유(확보), 왼쪽(빨강)=출원했지만 권리가 ' +
            '떠남(유출). 거래 활발 분류: 이전이 몰린 기술=시장에서 돈을 주고 살 만큼 가치가 확인된 ' +
            '영역입니다. 막대·노드·엣지 클릭 시 근거 특허가 열립니다.',
          renderOk: function (r, c, setTarget) {
            var k = r.kpi || {};
            var grid = Ui.el('<div class="kpi-grid" style="margin-bottom:10px"></div>');
            [[Ui.num(k.n_docs, 0), '분석 문헌'],
             [Ui.num(k.n_transferred, 0), '권리 이전 특허'],
             [Ui.pct(k.transfer_rate), '이전 비율'],
             [k.quality ? (Ui.num(k.quality.transferred_avg, 1) + ' vs ' +
               Ui.num(k.quality.kept_avg, 1)) : '-', '평균 피인용 (이전 vs 보유)']]
              .forEach(function (x) {
                grid.appendChild(Ui.el('<div class="kpi"><div class="kpi-value">' + Ui.esc(x[0]) +
                  '</div><div class="kpi-label">' + Ui.esc(x[1]) + '</div></div>'));
              });
            c.body.appendChild(grid);
            if (r.network) {
              var cyH = Ui.el('<div class="cy-holder"></div>');
              c.body.appendChild(cyH);
              var cy = Render.cytoscape(cyH, r.network, {
                onNode: function (d) {
                  Drill.open(d.drill, d.label + ' — 확보 ' + d.acquired + ' / 유출 ' + d.divested);
                }
              });
              setTarget({ kind: 'cy', cy: cy });
            }
            if (r.fig_net) {
              var nh = Ui.el('<div class="chart-holder"></div>');
              c.body.appendChild(nh);
              Render.plotly(nh, r.fig_net, plotlyDrill);
              if (!r.network) setTarget({ kind: 'plotly', el: nh });
            }
            if (r.fig_tech) {
              var th = Ui.el('<div class="chart-holder"></div>');
              c.body.appendChild(th);
              Render.plotly(th, r.fig_tech, plotlyDrill);
            }
            if ((r.top_pairs || []).length) {
              var rows = r.top_pairs.map(function (p) {
                var tr = document.createElement('tr');
                var td0 = document.createElement('td');
                td0.appendChild(drillCell(p.from + ' → ' + p.to, p.drill));
                tr.appendChild(td0);
                tr.insertAdjacentHTML('beforeend',
                  '<td class="num">' + Ui.num(p.n, 0) + '</td>' +
                  '<td>' + Ui.esc(p.tech) + '</td>' +
                  '<td>' + Ui.esc(p.period) + '</td>');
                return tr;
              });
              var tbl = Ui.el(simpleTable(['이전 (출원인 → 권리자)', '건수', '주요 기술분류', '출원 기간'], []));
              rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
              var wrap = Ui.el('<div style="overflow-x:auto;max-height:280px;overflow-y:auto;margin-top:8px"></div>');
              wrap.appendChild(tbl);
              c.body.appendChild(wrap);
            }
          }
        });
      } },
      { label: '유사도·중첩도', render: function (h) {
        analysisCard({
          analysis: 'company-dna', holder: h, title: '전략 유사도 · 포트폴리오 중첩도',
          help: '전략 유사도=기술 구성비 코사인, 중첩도=활동 분류 집합 Jaccard.',
          guide: '두 히트맵 모두 가로·세로축=기업이며 대각선은 자기 자신(=1)입니다. 전략 유사도: 셀 값=두 기업의 기술분류 구성비가 얼마나 비슷한지(코사인, 0~1) — 1에 가까울수록 같은 곳에 투자하는 직접 경쟁 관계. 포트폴리오 중첩도: 셀 값=두 기업이 활동하는 기술분류 집합의 겹침(Jaccard, 0~1). 읽는 법: 유사도는 높은데 중첩도가 낮으면 비중은 비슷하지만 세부 영역이 다른 잠재 경쟁자입니다.',
          renderOk: function (r, c, setTarget) {
            if (r.similarity) {
              var s = Ui.el('<div class="chart-holder"></div>');
              c.body.appendChild(s);
              Render.plotly(s, r.similarity);
              setTarget({ kind: 'plotly', el: s });
            }
            if (r.overlap) {
              var o = Ui.el('<div class="chart-holder"></div>');
              c.body.appendChild(o);
              Render.plotly(o, r.overlap);
            }
          }
        });
      } },
      { label: 'Patent Asset Index', render: function (h) {
        analysisCard({
          analysis: 'portfolio-index', holder: h,
          title: 'Patent Asset Index · Competitive Impact · Market Coverage (회사 선택 가능)',
          controls: multiCompanyControls('회사 선택'),
          help: '공개 방법론(Ernst & Omland 2011, Patent Asset Index)에 따라 TR(연도×기술분야 코호트 보정 피인용), MC(보호국 GNI 가중, 미국=1), CI=TR×MC, PAI=유효특허 CI 합계를 계산합니다. 상단에서 필요한 회사만 골라 비교할 수 있으며(지표 값은 전체 데이터 기준으로 계산되어 동일), 아래 지표 정의표와 각 차트의 해석 설명을 참고하세요.',
          renderOk: function (r, c, setTarget) {
            c.body.appendChild(definitionsTable(r.definitions, r.official_diff));
            var fb = Ui.el('<div class="chart-holder tall"></div>');
            c.body.appendChild(fb);
            Render.plotly(fb, r.family_bubble, plotlyDrill);
            setTarget({ kind: 'plotly', el: fb });
            c.body.appendChild(chartCap('X축=특허 패밀리 건수(양적 규모), Y축=평균 Competitive ' +
              'Impact(질적 수준, 1.0=평균), 버블 크기=패밀리 건수, 색=평균 Market Coverage, ' +
              '라벨=출원인. 읽는 법: 우상단=양·질 모두 우수한 선도기업, 좌상단=규모는 작지만 ' +
              '질이 높은 강소기업(협력·인수 검토 후보), 우하단=양 위주 포트폴리오. 버블 클릭 시 ' +
              '해당 출원인의 근거 특허가 열립니다.'));
            if (r.mc_bar) {
              var mc = Ui.el('<div class="chart-holder"></div>');
              c.body.appendChild(mc);
              Render.plotly(mc, r.mc_bar, plotlyDrill);
              c.body.appendChild(chartCap('X축=기업별 평균 Market Coverage. 산출 기준: ' +
                (r.mc_source || '') + '. 읽는 법: 값이 클수록 특허를 더 큰 시장(여러 국가)에서 ' +
                '보호하고 있다는 뜻으로, 글로벌 사업 의지와 권리 투자 규모를 보여줍니다.'));
            }
            var pai = Ui.el('<div class="chart-holder"></div>');
            c.body.appendChild(pai);
            Render.plotly(pai, r.rank, plotlyDrill);
            c.body.appendChild(chartCap('X축=Patent Asset Index(대상 특허 Competitive Impact 의 ' +
              '합계), Y축=기업. 읽는 법: 특허의 양과 질을 함께 반영한 포트폴리오 총 가치 순위입니다. ' +
              '건수 순위(기본 통계 탭)와 비교해 순위가 크게 다른 기업은 질적 편차가 큰 것입니다.'));
          }
        });
      } },
      { label: 'Portfolio 종합', render: function (h) {
        analysisCard({
          analysis: 'portfolio-index', holder: h,
          title: '포트폴리오 가치 지표 종합 (Patent Asset Index 방법론 · 회사 선택 가능)',
          controls: multiCompanyControls('회사 선택'),
          help: '공개 방법론(Ernst & Omland 2011)에 따른 PAI/CI/TR/MC 로 포트폴리오의 양과 질을 종합 진단합니다. 상단에서 필요한 회사만 골라 비교할 수 있습니다 (지표 값은 전체 데이터 기준으로 계산되어 동일). 각 지표의 정의·산식·해석은 아래 지표 정의표를, 각 차트의 읽는 법은 차트 아래 설명을 참고하세요.',
          renderOk: function (r, c, setTarget) {
            c.body.appendChild(definitionsTable(r.definitions, r.official_diff));
            var rank = Ui.el('<div class="chart-holder"></div>');
            c.body.appendChild(rank);
            Render.plotly(rank, r.rank, plotlyDrill);
            setTarget({ kind: 'plotly', el: rank });
            c.body.appendChild(chartCap('X축=Patent Asset Index(유효특허 CI 합계), Y축=기업. ' +
              '읽는 법: 포트폴리오 총 가치 순위 — 양(건수)과 질(CI)이 모두 반영되므로 건수가 ' +
              '적어도 질 높은 특허가 많으면 상위에 올 수 있습니다. 막대 클릭 시 해당 기업의 ' +
              '특허 목록이 열립니다.'));
            var bub = Ui.el('<div class="chart-holder tall"></div>');
            c.body.appendChild(bub);
            Render.plotly(bub, r.bubble, plotlyDrill);
            c.body.appendChild(chartCap('X축=대상 특허 수(양), Y축=평균 Competitive Impact(질, ' +
              '1.0=평균), 버블 크기=PAI, 색=최근 출원 성장률(초록=성장, 빨강=감소). 읽는 법: ' +
              'PAI 가 비슷해도 우상단 기업(질 중심)과 우하단 기업(양 중심)은 전략이 다릅니다. ' +
              '좌상단의 작지만 진한 초록 버블 = 질 높고 성장 중인 주목 기업입니다.'));
            if (r.trend) {
              var tr = Ui.el('<div class="chart-holder" style="min-height:320px"></div>');
              c.body.appendChild(tr);
              Render.plotly(tr, r.trend);
              c.body.appendChild(chartCap('X축=출원연도, Y축=그 해 출원된 특허들의 CI 합계 ' +
                '(상위 5개사). 읽는 법: 선이 최근으로 갈수록 높아지면 포트폴리오의 질이 개선되고 ' +
                '있다는 뜻입니다. 단, 최근 연도는 인용이 아직 축적되지 않아 낮게 보이는 경향이 ' +
                'TR 의 연도 보정으로 완화되지만 완전히 제거되지는 않습니다.'));
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
            c.body.appendChild(chartCap('포트폴리오 가치를 견인하는 개별 핵심특허 목록입니다. ' +
              'CI=TR×MC 이므로, TR 열이 큰 특허는 기술적 영향력이, MC 열이 큰 특허는 넓은 시장 ' +
              '보호가 가치의 원천입니다. 번호 클릭 시 서지 정보가 열립니다.'));
          }
        });
      } }
    ]);
  };

  /* ---------- 4. White Space & R&D ---------- */
  Views.whitespace = function (content) {
    makeTabs(content, [
      { label: 'Opportunity Matrix', render: function (h) { renderOpportunity(h); } },
      { label: '미점유 조합 (UpSet)', render: function (h) { renderComboUpset(h); } },
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
      analysis: 'opportunity', holder: h, title: 'Actionable White Space Map (자사 선택 가능)',
      controls: companySelectControls('자사(출원인) 선택'),
      help: 'X=매력도(가중 기하평균), Y=진입 가능성(1-권리장벽). 크기=관련 특허 수, 색=권리장벽. ◇=자사 역량 보유 — "자사"는 상단에서 선택한 출원인(공동출원 포함) 기준이며, 선택하지 않으면 데이터의 \'자사 특허 여부\' 컬럼(없으면 표시 안 함)을 사용합니다. 가중치 슬라이더는 서버 재계산 없이 즉시 반영됩니다.',
      renderOk: function (r, c, setTarget) {
        var holder = Ui.el('<div class="chart-holder tall"></div>');
        c.body.appendChild(holder);
        Render.plotly(holder, r.figure, plotlyDrill);
        setTarget({ kind: 'plotly', el: holder });
        // 가중치 슬라이더 (클라이언트 즉시 재계산 — 기본 축 보기에서 동작)
        sliderBox = Ui.el('<div style="margin-top:8px;border-top:1px dashed #e0e8ef;padding-top:8px">' +
          '<b style="font-size:12px">가중치 (즉시 반영)</b></div>');
        var labels = { growth: '성장률', new_entrants: '신규 출원인', combo_growth: '조합 증가',
          keyword_growth: '키워드 증가', problem_recurrence: '과제 반복', adjacency: '인접 연결성',
          barrier: '권리장벽 가중(진입 감점)' };
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

  function renderComboUpset(h) {
    analysisCard({
      analysis: 'combo-upset', holder: h,
      title: '미점유 조합 UpSet — 3개 이상 기술요소 교집합',
      help: '핵심 질문: "각 기술요소는 이미 알려져 있지만, 아직 함께 청구되지 않은 조합은 무엇인가?" ' +
        '2차원 히트맵으로는 보이지 않는 3개 이상 요소의 교집합을 UpSet 형식으로 보여주고, ' +
        '개별 요소는 혼잡하지만 결합 청구가 비어 있는 미점유 조합 후보를 기대-실제 격차 점수로 도출합니다.',
      guide: '위 막대: 높이=해당 요소 조합(아래 점들이 표시)의 특허 수, 색=유효특허 비율' +
        '(초록=대부분 유효, 빨강=대부분 소멸, 회색=법적상태 정보가 없어 판정 불가), 굵은 테두리=최근 3년 출원 있음. ' +
        '아래 매트릭스: 각 세로줄이 하나의 조합이며 진한 점=조합에 포함된 요소, 점을 잇는 ' +
        '세로선=다중 요소 교집합. 막대 클릭 시 해당 조합의 근거 특허가 열립니다. ' +
        '읽는 법: 왼쪽의 큰 막대는 이미 혼잡한 조합(경쟁 심함), 미점유 후보 표의 조합은 ' +
        '개별 요소 활동량 대비 결합 청구가 비어 있는 white space 입니다 — 기술적 실현 가능성과 ' +
        '선행문헌 검토가 반드시 뒤따라야 합니다.',
      renderOk: function (r, c, setTarget) {
        var holder = Ui.el('<div class="chart-holder tall"></div>');
        c.body.appendChild(holder);
        Render.plotly(holder, r.figure, plotlyDrill);
        setTarget({ kind: 'plotly', el: holder });
        if (r.gaps && r.gaps.length) {
          c.body.appendChild(Ui.el('<div style="font-weight:700;font-size:12.5px;margin:10px 0 4px">' +
            '🕳️ 미점유 조합 후보 (기대 대비 결합 청구 공백 — 격차 점수 순)</div>'));
          var rows = r.gaps.map(function (g) {
            var tr = document.createElement('tr');
            var td0 = document.createElement('td');
            (g.elements || []).forEach(function (e, i) {
              if (i) td0.appendChild(document.createTextNode(' + '));
              td0.appendChild(Ui.el('<span class="badge">' + Ui.esc(e) + '</span>'));
            });
            tr.appendChild(td0);
            var elemCounts = (g.elements || []).map(function (e) {
              return Ui.esc(e) + ' ' + Ui.num((g.element_counts || {})[e], 0) + '건';
            }).join(', ');
            tr.insertAdjacentHTML('beforeend',
              '<td class="num">' + Ui.num(g.actual, 0) + '</td>' +
              '<td class="num">' + Ui.num(g.expected, 1) + '</td>' +
              '<td class="num"><b>' + Ui.num(g.gap_score, 1) + '</b></td>' +
              '<td>' + elemCounts + '</td>' +
              '<td>' + (g.all_recent_active ?
                '<span class="badge good">전 요소 최근 활동</span>' : '-') + '</td>');
            return tr;
          });
          var tbl = Ui.el(simpleTable(
            ['요소 조합', '실제 결합 청구', '기대 건수(독립 가정)', '격차 점수', '개별 요소 활동량', '최근성'], []));
          rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
          var wrap = Ui.el('<div style="overflow-x:auto"></div>');
          wrap.appendChild(tbl);
          c.body.appendChild(wrap);
          c.body.appendChild(chartCap('기대 건수=전체 문헌 수 × 각 요소 출현확률의 곱(요소 독립 가정). ' +
            '실제 결합 청구가 기대의 15% 이하이면서 기대 1.5건 이상인 조합만 후보로 표시합니다. ' +
            '제품 요구사항 적합도 점수는 요구사항 데이터가 없어 격차 점수와 최근성으로 대체합니다.'));
        } else {
          c.body.appendChild(Ui.el('<div class="status-empty">기대 대비 비어 있는 조합이 ' +
            '발견되지 않았습니다 — 상위 요소 조합은 대부분 이미 청구되어 있습니다.</div>'));
        }
      }
    });
  }

  function renderProblemSolution(h) {
    analysisCard({
      analysis: 'problem-solution', holder: h, title: '문제–해결수단 매트릭스 (C축 × B축)',
      help: '행=해결과제(C축 기술분류), 열=해결수단(B축 기술분류). B축에 해결수단 분류, C축에 해결과제 분류가 ' +
        '매핑된 경우에만 그려집니다 — 미매핑이면 비활성 안내가 표시됩니다. 색=최근 성장률, hover=건수·유효비율·상위 출원인. ' +
        '셀 클릭 시 관련 특허·추이·대표 청구항 패널 표시. ' +
        '"의미 그룹" 보기는 해결과제·해결수단 텍스트 컬럼이 있을 때 유사 문구를 KR-SBERT 임베딩으로 묶어 표현만 다른 중복을 통합합니다.',
      controls: function (c, reload) {
        var modeSel = Ui.el('<select><option value="">원문 기준</option>' +
          '<option value="semantic">의미 그룹 (임베딩)</option></select>');
        modeSel.addEventListener('change', function () {
          reload({ group_mode: modeSel.value || null });
        });
        c.controls.prepend(modeSel);
      },
      renderOk: function (r, c, setTarget) {
        if (r.group_mode === 'semantic') {
          var gh = Ui.el('<div class="chart-holder tall"></div>');
          c.body.appendChild(gh);
          Render.plotly(gh, r.figure, plotlyDrill);
          setTarget({ kind: 'plotly', el: gh });
          if (r.methods) {
            c.body.appendChild(Ui.el('<div style="margin:6px 0;color:#647b8d;font-size:11.5px">방법: 임베딩 ' +
              Ui.esc(r.methods.embedding) + ' · 군집 ' + Ui.esc(r.methods.clustering) + '</div>'));
          }
          function groupTable(title, groups, kind) {
            c.body.appendChild(Ui.el('<div style="font-weight:700;font-size:12.5px;margin:10px 0 4px">' +
              Ui.esc(title) + '</div>'));
            var rows = (groups || []).map(function (g) {
              var tr = document.createElement('tr');
              var td0 = document.createElement('td');
              var drill = { type: 'cell_group' };
              drill[kind] = g.members;
              td0.appendChild(drillCell(g.label, drill));
              tr.appendChild(td0);
              tr.insertAdjacentHTML('beforeend',
                '<td class="num">' + Ui.num(g.n, 0) + '</td>' +
                '<td>' + (g.members || []).slice(0, 6).map(function (m) {
                  return '<span class="badge">' + Ui.esc(String(m).slice(0, 30)) + '</span>';
                }).join('') + ((g.members || []).length > 6 ? ' 외 ' + (g.members.length - 6) : '') + '</td>');
              return tr;
            });
            var tbl = Ui.el(simpleTable(['그룹 (대표 문구)', '건수', '포함 문구'], []));
            rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
            var wrap = Ui.el('<div style="overflow-x:auto;max-height:260px;overflow-y:auto"></div>');
            wrap.appendChild(tbl);
            c.body.appendChild(wrap);
          }
          groupTable('해결과제 그룹 (행)', r.problem_groups, 'problems');
          groupTable('해결수단 그룹 (열)', r.solution_groups, 'solutions');
          c.body.appendChild(chartCap('행·열=임베딩 코사인 유사도로 묶인 과제·수단 그룹(라벨=그룹 내 최다 빈도 문구), ' +
            '셀=해당 그룹 조합의 특허 수. 원문 매트릭스에서는 표현이 달라 흩어져 보이던 조합이 통합되어 ' +
            '실질적인 밀집·공백을 판단하기 좋습니다. 셀·그룹 클릭 시 그룹 전체 문구의 특허가 열립니다. ' +
            '그룹이 너무 크게/작게 묶이면 Settings → 임계값 ps_group_distance 를 조정하세요.'));
          return;
        }
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
          // Excel 보조 시트: 축약 없는 전체 문구 라벨 + 건수 매트릭스
          if (r.figure.counts_z) {
            holder.__iplsExtraSheets = [{
              name: '건수 (전체 라벨)',
              columns: ['해결과제(행) \\ 해결수단(열)'].concat(r.solutions || []),
              rows: (r.problems || []).map(function (p, i) {
                return [p].concat(r.figure.counts_z[i] || []);
              })
            }];
          }
          // 축에는 축약 라벨이 표시되므로 클릭 시 전체 문구로 역변환
          var probByLabel = {}, solByLabel = {};
          (r.problem_labels || []).forEach(function (l, i) { probByLabel[l] = r.problems[i]; });
          (r.solution_labels || []).forEach(function (l, i) { solByLabel[l] = r.solutions[i]; });
          holder.on('plotly_click', function (ev) {
            var pt = ev.points && ev.points[0];
            if (!pt) return;
            openCell(probByLabel[pt.y] || pt.y, solByLabel[pt.x] || pt.x);
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
              layout: { margin: { l: 40, r: 10, t: 10, b: 30 }, height: 190,
                        xaxis: { tickformat: 'd', hoverformat: 'd' } }
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
          analysis: 'citation-diffusion', holder: h, title: '핵심특허 영향력 (Influence Score · 출원인 선택 가능)',
          controls: companySelectControls('출원인 선택'),
          help: 'Influence = Σ(표준화 지표×가중치): 직접·간접 피인용, 타 분류/타 기업 확산, 패밀리 확장, 유지·권리범위. 가중치는 Settings 에서 조정. 출원인을 선택하면 그 회사 특허(공동출원 포함)만 순위에 표시되며, 점수는 전체 데이터 기준으로 계산되어 비교 가능합니다.',
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
          help: '독립청구항 임베딩→UMAP/PCA 2D→HDBSCAN 클러스터→KDE 밀도. 임베딩 우선순위: ① 사전 계산 임베딩 컬럼 ② KR-SBERT 특허 특화 모델(snunlp, 기본) ③ TF-IDF 폴백 — 실제 사용된 방식은 차트 아래 "방법"에 표시됩니다. 점=문헌(크기=피인용, 투명도=권리 유효성, 테두리=등록). FTO 판단이 아닌 우선 검토 스크리닝 도구입니다.',
          controls: function (c, reload) {
            var t = Ui.el('<select><option value="">전체 분류</option></select>');
            ((State.filterOptions || {}).tech || []).slice(0, 300).forEach(function (x) {
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
          help: '⚠ 네트워크의 노드는 발명자가 아니라 기업(출원인)입니다 — 발명자 개인의 소속 변화를 ' +
            '집계해 "어느 회사에서 어느 회사로 인력이 이동했는가"를 요약하기 때문입니다. ' +
            '개별 발명자 이름은 아래 "이동 발명자 목록" 표와 화살표(엣지) 클릭에서 확인할 수 있습니다. ' +
            '동명이인은 공동발명자·분류·시점·국가·희소성 기반 신뢰도로 식별하며 임계값 미만은 "추정 이동"으로 기본 제외.',
          controls: function (c, reload) {
            var chk = Ui.el('<label style="font-size:12px"><input type="checkbox"> 추정 이동 포함</label>');
            chk.querySelector('input').addEventListener('change', function (ev) {
              reload({ include_uncertain: ev.target.checked });
            });
            c.controls.prepend(chk);
          },
          renderOk: function (r, c, setTarget) {
            if (r.meta && r.meta.warning) {
              c.body.appendChild(Ui.el('<div class="disclaimer" style="border-left:3px solid #E15759;' +
                'padding-left:8px;font-weight:600">' + Ui.esc(r.meta.warning) + '</div>'));
            }
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
            if ((r.moves || []).length) {
              c.body.appendChild(Ui.el('<div style="font-weight:700;font-size:12.5px;margin:10px 0 4px">' +
                '👤 이동 발명자 목록 (이름 클릭 시 특허 이력)</div>'));
              var rows = r.moves.map(function (m) {
                var tr = document.createElement('tr');
                var td0 = document.createElement('td');
                td0.appendChild(drillCell(m.inventor, m.drill));
                tr.appendChild(td0);
                tr.insertAdjacentHTML('beforeend',
                  '<td>' + Ui.esc(m.from) + ' → ' + Ui.esc(m.to) + '</td>' +
                  '<td class="num">' + m.year + '</td>' +
                  '<td class="num">' + Ui.num(m.confidence, 2) + '</td>' +
                  '<td>' + (m.label === '확인 이동' ? '<span class="badge good">확인 이동</span>' :
                    '<span class="badge warn">' + Ui.esc(m.label) + '</span>') + '</td>' +
                  '<td>' + (m.techs || []).map(function (t) {
                    return '<span class="badge">' + Ui.esc(t) + '</span>';
                  }).join('') + '</td>');
                return tr;
              });
              var tbl = Ui.el(simpleTable(['발명자', '이동 경로', '연도', '신뢰도', '구분', '관련 기술'], []));
              rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
              var wrap = Ui.el('<div style="overflow-x:auto;max-height:300px;overflow-y:auto;margin-top:4px"></div>');
              wrap.appendChild(tbl);
              c.body.appendChild(wrap);
            }
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
      } },
      { label: '의미 기반 영향력 (임베딩)', render: function (h) {
        analysisCard({
          analysis: 'semantic-influence', holder: h,
          title: '의미 기반 인용/영향력 대체 지표',
          help: '인용 데이터가 부실한 한국 특허의 약점을 임베딩으로 보완합니다. 어떤 특허 이후 ' +
            '의미적으로 매우 유사한(코사인 ≥ 임계값) 후속 특허가 여러 타 기업에서 출원되었으면 ' +
            '명시적 인용이 없어도 영향력 신호로 봅니다. 이는 인용의 대체 신호일 뿐 후속 출원이 ' +
            '해당 특허를 참고했다는 인과관계·모방의 증거가 아닙니다.',
          guide: 'Sankey: 왼쪽=원천 특허(영향력 상위), 오른쪽=유사 후속 특허를 낸 기업, ' +
            '흐름 두께=유사 후속 출원 수 — 넓게 퍼질수록 여러 회사가 같은 의미 영역으로 ' +
            '따라 들어온 것입니다. 산점도: X축=명시적 피인용 수, Y축=의미 유사 후속 수. ' +
            '좌상단(피인용 적음×후속 많음)=인용 통계에 잡히지 않는 숨은 영향력 특허입니다. ' +
            '표의 행을 클릭하면 원천+후속 특허 목록이 열립니다.',
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="chart-holder tall"></div>');
            c.body.appendChild(holder);
            Render.plotly(holder, r.sankey);
            setTarget({ kind: 'plotly', el: holder });
            if (r.scatter) {
              var sh = Ui.el('<div class="chart-holder"></div>');
              c.body.appendChild(sh);
              Render.plotly(sh, r.scatter, plotlyDrill);
            }
            var rows = (r.top_patents || []).map(function (x) {
              var tr = document.createElement('tr');
              var td0 = document.createElement('td');
              td0.appendChild(drillCell(x.id, x.drill));
              tr.appendChild(td0);
              tr.insertAdjacentHTML('beforeend',
                '<td>' + Ui.esc(x.title || '') + '</td>' +
                '<td>' + Ui.esc(x.applicant) + '</td>' +
                '<td class="num">' + x.year + '</td>' +
                '<td class="num">' + Ui.num(x.followers, 0) + '</td>' +
                '<td class="num">' + Ui.num(x.cross_followers, 0) + ' (' + x.companies + '개사)</td>' +
                '<td class="num">' + Ui.num(x.avg_sim, 2) + '</td>' +
                '<td class="num">' + (x.cites !== null && x.cites !== undefined ? Ui.num(x.cites, 0) : '-') + '</td>');
              return tr;
            });
            var tbl = Ui.el(simpleTable(
              ['원천 특허', '명칭', '출원인', '연도', '의미 후속', '타기업 후속', '평균 유사도', '피인용'], []));
            rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
            var wrap = Ui.el('<div style="overflow-x:auto;margin-top:8px"></div>');
            wrap.appendChild(tbl);
            c.body.appendChild(wrap);
            if (r.methods) {
              c.body.appendChild(Ui.el('<div style="margin-top:6px;color:#647b8d;font-size:11.5px">방법: 임베딩 ' +
                Ui.esc(r.methods.embedding) + ' · 텍스트 ' + Ui.esc(r.methods.text_source) +
                ' · 유사도 임계값 ' + r.methods.threshold + '</div>'));
            }
          }
        });
      } },
      { label: '권리 중첩 네트워크 (임베딩)', render: function (h) {
        analysisCard({
          analysis: 'similarity-network', holder: h,
          title: '특허 유사도 네트워크 — 권리 중첩 그래프',
          help: '임베딩 코사인 유사도가 임계값(기본 0.85) 이상인 특허쌍을 엣지로 연결한 네트워크입니다. ' +
            '촘촘하게 뭉친 덩어리=유사 특허가 밀집한 권리 중첩 후보 지대, 덩어리 내부를 잇는 ' +
            '관절점=브리지 특허. 의미 유사도 신호이며 법적 권리범위 중첩 판단(FTO)이 아닙니다.',
          guide: '노드=특허(색=출원인, 크기=연결 수, 빨간 테두리=브리지 특허), 엣지=유사도 ' +
            '임계값 이상 쌍(두꺼울수록 더 유사). 읽는 법: 한 색으로 뭉친 덩어리=특정 기업이 장악한 ' +
            '중첩 지대(그 기업의 요새), 여러 색이 섞인 덩어리=경쟁이 밀집한 격전지, ' +
            '브리지 특허=군집 사이를 잇는 구조적 요충 문헌. 노드/엣지 클릭 시 해당 특허가 열립니다. ' +
            '임계값을 낮추면 더 느슨한 유사까지 연결됩니다.',
          controls: function (c, reload) {
            var inp = Ui.el('<input type="number" step="0.05" min="0.5" max="0.99" ' +
              'style="width:70px" title="코사인 유사도 임계값" placeholder="0.85">');
            inp.addEventListener('change', function () {
              reload({ threshold: Number(inp.value) || null });
            });
            var lbl = Ui.el('<span style="font-size:11.5px;color:#647b8d">임계값</span>');
            c.controls.prepend(inp); c.controls.prepend(lbl);
          },
          renderOk: function (r, c, setTarget) {
            var holder = Ui.el('<div class="cy-holder" style="height:520px"></div>');
            c.body.appendChild(holder);
            var cy = Render.cytoscape(holder, r.network, {
              onNode: function (d) {
                Drill.open(d.drill, (d.full_id || d.label) + ' — ' + (d.title || ''));
              },
              onEdge: function (d) { Drill.open(d.drill, '유사쌍 (코사인 ' + d.weight + ')'); }
            });
            setTarget({ kind: 'cy', cy: cy });
            var rows = (r.components || []).map(function (x) {
              var tr = document.createElement('tr');
              var td0 = document.createElement('td');
              td0.appendChild(drillCell('지대 #' + (x.component + 1), x.drill));
              tr.appendChild(td0);
              tr.insertAdjacentHTML('beforeend',
                '<td class="num">' + Ui.num(x.n, 0) + '</td>' +
                '<td>' + Ui.esc(x.dominant) + (x.dominant_share !== null && x.dominant_share !== undefined ?
                  ' (' + Ui.pct(x.dominant_share) + ')' : '') + '</td>' +
                '<td class="num">' + (x.active_ratio !== null && x.active_ratio !== undefined ?
                  Ui.pct(x.active_ratio) : '-') + '</td>' +
                '<td class="num">' + (x.avg_sim !== null && x.avg_sim !== undefined ?
                  Ui.num(x.avg_sim, 2) : '-') + '</td>' +
                '<td>' + (x.bridges || []).map(function (b) {
                  return '<span class="badge warn">' + Ui.esc(String(b)) + '</span>';
                }).join('') + '</td>');
              return tr;
            });
            var tbl = Ui.el(simpleTable(
              ['중첩 지대', '특허 수', '지배 출원인', '유효 비율', '평균 유사도', '브리지 특허'], []));
            rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
            var wrap = Ui.el('<div style="overflow-x:auto;max-height:300px;overflow-y:auto;margin-top:8px"></div>');
            wrap.appendChild(tbl);
            c.body.appendChild(wrap);
            if (r.methods) {
              c.body.appendChild(Ui.el('<div style="margin-top:6px;color:#647b8d;font-size:11.5px">방법: 임베딩 ' +
                Ui.esc(r.methods.embedding) + ' · 임계값 ' + r.methods.threshold +
                (r.methods.edge_truncated ? ' · 엣지 상한 절단됨(유사도 상위만 표시)' : '') + '</div>'));
            }
          }
        });
      } }
    ]);
  };

  /* ---------- 6. Data Quality ---------- */
  Views.quality = function (content) {
    makeTabs(content, [
      { label: '검증 리포트', render: renderVerificationReport },
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

  function renderVerificationReport(h) {
    var c = card('검증 리포트 — 이 앱은 어떻게 검증되었는가',
      '아래 수치는 전부 실측입니다: 테스트 수는 빌드 시 저장소에서 직접 센 값, ' +
      '셀프 체크는 지금 로딩된 데이터로 이 자리에서 다시 계산한 값입니다. ' +
      '확인 불가 항목은 통과로 위장하지 않고 그대로 표시합니다.');
    h.appendChild(c.root);
    c.body.innerHTML = '<div class="status-empty">불러오는 중…</div>';
    Api.post('/api/quality-report', { filters: State.filters }, '검증 리포트 계산 중…')
      .then(function (r) {
        c.body.innerHTML = '';
        if (r.status !== 'ok') { c.body.innerHTML = Render.statusBlock(r); return; }
        var b = r.build || {};
        var badges = '';
        if (b.test_functions) {
          badges += '<span class="badge good">자동 테스트 ' + Ui.num(b.test_functions, 0) +
            '개 (' + Ui.num(b.test_files || 0, 0) + '개 파일, 실측 집계)</span>';
        }
        if (b.modules) badges += '<span class="badge">병합 모듈 ' + b.modules + '개</span>';
        if (b.built_at) badges += '<span class="badge">빌드 ' + Ui.esc(b.built_at) + '</span>';
        var s = r.summary || {};
        badges += '<span class="badge good">셀프 체크 통과 ' + (s.pass || 0) + '</span>' +
          (s.warn ? '<span class="badge warn">주의 ' + s.warn + '</span>' : '') +
          (s.na ? '<span class="badge">확인 불가 ' + s.na + '</span>' : '');
        c.body.appendChild(Ui.el('<div style="margin-bottom:10px">' + badges + '</div>'));

        c.body.appendChild(Ui.el('<b style="font-size:13px">① 데이터 정합성 셀프 체크 ' +
          '(지금 로딩된 데이터 · 즉석 독립 재계산)</b>'));
        var rows = (r.checks || []).map(function (x) {
          var cls = x.status === '통과' ? 'good' : (x.status === '주의' ? 'warn' : '');
          return '<td>' + Ui.esc(x.name) + '</td><td><span class="badge ' + cls + '">' +
            Ui.esc(x.status) + '</span></td><td>' + Ui.esc(x.detail) + '</td>';
        });
        c.body.appendChild(Ui.el(simpleTable(['점검 항목', '판정', '상세 (재계산 근거)'], rows)));

        c.body.appendChild(Ui.el('<b style="font-size:13px;display:block;margin-top:14px">' +
          '② 검증 레지스트리 — 핵심 계산이 검증된 방법과 근거 테스트 (전부 저장소에 실존)</b>'));
        var rows2 = (r.registry || []).map(function (x) {
          return '<td>' + Ui.esc(x.area) + '</td><td>' + Ui.esc(x.claim) + '</td><td>' +
            Ui.esc(x.method) + '</td><td style="color:#93a5b4;font-size:11px">' +
            Ui.esc(x.test) + '</td>';
        });
        var wrap2 = Ui.el('<div style="max-height:340px;overflow:auto;margin-top:6px"></div>');
        wrap2.appendChild(Ui.el(simpleTable(['검증 영역', '검증된 내용', '방법', '근거 테스트'], rows2)));
        c.body.appendChild(wrap2);

        c.body.appendChild(Ui.el('<b style="font-size:13px;display:block;margin-top:14px">' +
          '③ 개발 원칙 (코드가 실제로 따르는 규칙만 기재)</b>'));
        c.body.appendChild(Ui.el('<ul style="font-size:12px;color:#46607a;margin:6px 0 0 18px">' +
          (r.principles || []).map(function (p) { return '<li>' + Ui.esc(p) + '</li>'; }).join('') +
          '</ul>'));
        if (r.insight && r.insight.sentences) {
          c.body.appendChild(Ui.el('<div class="chart-guide" style="margin-top:10px"><b>요약</b>' +
            Ui.esc(r.insight.sentences.join(' ')) + '</div>'));
        }
      }).catch(errToast);
  }

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
  /* ---------- 인사이트 보관함 ---------- */
  Views.insights = function (content) {
    var c = card('🗂️ LLM 인사이트 보관함',
      '각 차트에서 "LLM 인사이트 생성" 버튼(또는 AI 챗 질문)으로 만든 인사이트가 자동 저장됩니다 ' +
      '(최근 300건, Backend 재시작 후에도 유지). 기본으로는 지금 분석 중인 작업의 인사이트만 ' +
      '보이고, 이전 작업들은 아래 작업 선택에서 골라 따로 볼 수 있습니다. 체크한 항목(미선택 시 ' +
      '현재 보이는 작업 전체)을 PPT 보고서(.pptx)로 내려받을 수 있습니다.');
    content.appendChild(c.root);
    var groupBar = Ui.el('<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;align-items:center"></div>');
    c.body.appendChild(groupBar);
    var toolbar = Ui.el('<div style="display:flex;gap:8px;margin-bottom:10px;align-items:center"></div>');
    var pptBtn = Ui.el('<button class="btn small primary">선택 항목 PPT 다운로드 (미선택=현재 작업 전체)</button>');
    var refreshBtn = Ui.el('<button class="btn small">새로고침</button>');
    toolbar.appendChild(pptBtn);
    toolbar.appendChild(refreshBtn);
    c.body.appendChild(toolbar);
    var listEl = Ui.el('<div></div>');
    c.body.appendChild(listEl);

    var allItems = [];
    var currentDs = null;
    var selectedGroup = null;   // dataset key of the group being viewed

    function groupKey(it) { return it.dataset || '__none__'; }
    function selectedIds() {
      return Array.from(listEl.querySelectorAll('input[type="checkbox"]:checked'))
        .map(function (cb) { return cb.value; });
    }
    function visibleItems() {
      return allItems.filter(function (it) { return groupKey(it) === selectedGroup; });
    }

    function renderGroupBar() {
      groupBar.innerHTML = '';
      var groups = {};
      allItems.forEach(function (it) {
        var k = groupKey(it);
        if (!groups[k]) groups[k] = { key: k, label: it.dataset_label || '작업 미지정', n: 0 };
        groups[k].n += 1;
      });
      // 현재 작업은 저장 항목이 없어도 칩으로 표시해 위치를 알 수 있게 함
      if (currentDs && !groups[currentDs]) {
        groups[currentDs] = { key: currentDs, label: currentDs, n: 0 };
      }
      var keys = Object.keys(groups);
      // 현재 작업 그룹을 맨 앞으로
      keys.sort(function (a, b) {
        if (a === currentDs) return -1;
        if (b === currentDs) return 1;
        return 0;
      });
      groupBar.appendChild(Ui.el('<span style="font-size:12px;color:#647b8d">작업:</span>'));
      keys.forEach(function (k) {
        var g = groups[k];
        var isCur = k === currentDs;
        var active = k === selectedGroup;
        var chip = Ui.el('<button class="btn small' + (active ? ' primary' : '') + '">' +
          (isCur ? '📌 현재 작업 — ' : '') + Ui.esc(g.label) + ' (' + g.n + ')</button>');
        chip.addEventListener('click', function () {
          selectedGroup = k;
          renderGroupBar();
          renderList();
        });
        groupBar.appendChild(chip);
      });
      if (!keys.length) {
        groupBar.appendChild(Ui.el('<span style="color:#93a5b4;font-size:12px">저장된 작업 없음</span>'));
      }
    }

    function renderList() {
      listEl.innerHTML = '';
      var items = visibleItems();
      if (!items.length) {
        var isCur = selectedGroup === currentDs;
        listEl.innerHTML = '<div class="status-empty">' +
          (isCur ? '현재 작업에서 생성된 인사이트가 없습니다 — 각 차트에서 "LLM 인사이트 생성"을 ' +
            '실행하면 여기에 쌓입니다 (Settings 에서 LLM 인사이트 활성화 필요). 이전 작업의 ' +
            '인사이트는 위의 작업 버튼에서 볼 수 있습니다.'
            : '이 작업의 저장된 인사이트가 없습니다.') + '</div>';
        return;
      }
      items.forEach(function (it) {
          var row = Ui.el('<div style="border:1px solid #e8eff5;border-radius:8px;padding:10px 12px;margin-bottom:8px"></div>');
          var head = Ui.el('<div style="display:flex;gap:8px;align-items:center"></div>');
          var cb = Ui.el('<input type="checkbox" value="' + Ui.esc(it.id) + '">');
          head.appendChild(cb);
          head.appendChild(Ui.el('<span class="badge' + (it.kind === 'chat' ? '' : ' good') + '">' +
            (it.kind === 'chat' ? '챗' : '리포트') + '</span>'));
          var titleSpan = Ui.el('<b style="flex:1;cursor:pointer"></b>');
          titleSpan.textContent = it.title || it.analysis;
          head.appendChild(titleSpan);
          head.appendChild(Ui.el('<span style="color:#93a5b4;font-size:11px;white-space:nowrap">' +
            Ui.esc(it.analysis) + ' · ' + Ui.esc(it.created_at) +
            (it.dataset ? ' · ' + Ui.esc(it.dataset) : '') + '</span>'));
          var delBtn = Ui.el('<button class="btn small">삭제</button>');
          delBtn.addEventListener('click', function () {
            Api.post('/api/insights-log/delete', { id: it.id }).then(fetchItems).catch(errToast);
          });
          head.appendChild(delBtn);
          row.appendChild(head);
          var detail = Ui.el('<div style="display:none;margin-top:8px;border-top:1px dashed #e0e8ef;padding-top:8px"></div>');
          if (it.has_image) {
            var nImg = it.n_images || 1;
            head.appendChild(Ui.el('<span class="badge">📊 차트 ' +
              (nImg > 1 ? nImg + '개' : '포함') + '</span>'));
            for (var ii = 0; ii < nImg; ii++) {
              var img = Ui.el('<img style="max-width:100%;max-height:340px;border:1px solid #e8eff5;border-radius:6px;margin-bottom:8px" loading="lazy">');
              img.src = backendUrl('/api/insights-log/image?id=' +
                encodeURIComponent(it.id) + '&i=' + ii);
              detail.appendChild(img);
            }
          }
          var ul = document.createElement('ul');
          ul.style.cssText = 'padding-left:18px;font-size:12.5px;line-height:1.7';
          (it.sentences || []).forEach(function (s) {
            var li = document.createElement('li');
            li.textContent = s;
            if (String(s).indexOf('[') === 0) { li.style.fontWeight = '700'; li.style.listStyle = 'none'; li.style.marginLeft = '-14px'; }
            ul.appendChild(li);
          });
          detail.appendChild(ul);
          row.appendChild(detail);
          titleSpan.addEventListener('click', function () {
            detail.style.display = detail.style.display === 'none' ? '' : 'none';
          });
          listEl.appendChild(row);
      });
    }

    function fetchItems() {
      Api.get('/api/insights-log').then(function (d) {
        allItems = d.items || [];
        currentDs = d.current_dataset || null;
        var keys = {};
        allItems.forEach(function (it) { keys[groupKey(it)] = true; });
        // 기본은 현재 작업 그룹. 현재 작업에 항목이 없어도 비어있음 안내를 위해 유지.
        if (selectedGroup === null || (!keys[selectedGroup] && selectedGroup !== currentDs)) {
          selectedGroup = currentDs || Object.keys(keys)[0] || '__none__';
        }
        renderGroupBar();
        renderList();
      }).catch(errToast);
    }

    pptBtn.addEventListener('click', function () {
      var ids = selectedIds();
      if (!ids.length) ids = visibleItems().map(function (it) { return it.id; });
      if (!ids.length) { Ui.toast('내보낼 인사이트가 없습니다.', 'error'); return; }
      Api.download('/api/insights-report', { ids: ids },
        'ip_landscape_insights.pptx').catch(errToast);
    });
    refreshBtn.addEventListener('click', fetchItems);
    fetchItems();
  };

  /* ---------- 사용 설명서 ---------- */
  Views.manual = function (content) {
    function section(title, bodyHtml) {
      var c = card(title);
      c.body.innerHTML = bodyHtml;
      content.appendChild(c.root);
    }
    section('🚀 시작하기 (4단계)',
      '<ol style="padding-left:18px;line-height:1.9">' +
      '<li><b>데이터 준비</b> — Settings &amp; Admin → "📤 엑셀 업로드"에서 <b>작업자 이름·작업명을 입력</b>하고 WIPS Excel 을 직접 올리면 서버에 저장되고 바로 분석 Dataset 으로 설정됩니다 (저장된 작업은 목록에서 언제든 다시 불러오기 가능). 또는 Flow 에 이미 있는 Dataset 을 선택해도 됩니다.</li>' +
      '<li><b>컬럼 매핑 확인</b> — Settings → 컬럼 매핑에서 자동 추천 결과를 확인하고, 잘못 잡힌 항목은 직접 수정 후 저장합니다. ' +
      '각 컬럼의 "예시 값"으로 실제 데이터를 확인할 수 있습니다.</li>' +
      '<li><b>분석 단위 선택</b> — 문헌(건별) 또는 패밀리 대표 중 선택합니다. 지정국 진입 시차 등 일부 분석은 문헌 단위가 필요합니다. <b>공동출원 집계 방식</b>(공동출원인 각각 집계 / 대표 출원인만)도 이 단계에서 Settings → 분석 설정으로 정해 두세요 — 출원인 순위·매트릭스·버블 등 출원인별 차트의 집계 기준이 됩니다.</li>' +
      '<li><b>분석 목적 선택</b> — 업로드 직후(또는 Settings → 분석 설정, 좌측 🎯 목적 맞춤 분석 메뉴) 기술 동향 / 경쟁사 / R&amp;D 방향 / White Space / 특허 회피 / FTO / 포트폴리오 평가 / M&amp;A·투자 / 국가 R&amp;D / 라이선스 중 목적을 고르면, 그 목적에 맞는 차트가 <b>우선순위·이유·바로가기</b>와 함께 추천됩니다. 목적은 언제든 변경 가능하며 분석 값 자체는 바뀌지 않습니다.</li>' +
      '<li><b>분석 시작</b> — 목적 맞춤 추천 순서대로 보거나, 좌측 메뉴를 자유롭게 탐색하세요. 필수 컬럼이 없는 분석은 비활성 안내와 함께 필요한 매핑을 알려줍니다.</li></ol>' +
      '<div class="disclaimer">모든 분석은 매핑된 실제 데이터로만 계산되며 값을 임의로 만들지 않습니다. 데이터가 없는 항목은 "계산 불가 + 사유"로 표시됩니다.</div>');
    section('🗺️ 메뉴 안내',
      '<table class="ipls-table"><thead><tr><th>메뉴</th><th>내용</th></tr></thead><tbody>' +
      '<tr><td>🎯 목적 맞춤 분석</td><td>분석 목적(기술 동향·경쟁사·R&amp;D 방향·White Space·특허 회피·FTO·포트폴리오·M&amp;A·국가 R&amp;D·라이선스) 선택 → 목적별 추천 차트를 우선순위·이유와 함께 표시, [열기]로 바로 이동. 특허 회피·FTO 목적에는 법률 자문 아님 고지가 함께 표시됩니다.</td></tr>' +
      '<tr><td>📊 Executive Overview</td><td>경영 요약(KPI·경보·BCG 매트릭스·경쟁 포지션) + 경영 차트 6종: 📅만료 절벽 / 💰R&amp;D 효율 사분면 / 👤키맨 리스크 / ⏱️추격 시계 / 🚨위협 레이더 / ✂️포트폴리오 다이어트 (탭마다 자사 기준 선택 가능)</td></tr>' +
      '<tr><td>📈 전체 동향</td><td>포트폴리오 전체의 기본 현황: 연도별 출원 동향(출원인 선택 가능), 국가별 분포·출원인 순위·활동 매트릭스, 심화 분석(심사기간·만료 타임라인·청구항·공동출원·IPC)</td></tr>' +
      '<tr><td colspan="2" style="background:#f4f8fb;font-weight:700">🔬 기술 분석 — "어떤 기술이 어디로 가는가"</td></tr>' +
      '<tr><td>🔬 기술 분석</td><td>기술분류 동향(출원인 선택 가능), 기술분류 트리맵(대·중·소 계층, 면적=문헌 수), 기술×연도 버블(대·중·소 선택 + 최대 3사 비교), 기술 생애주기 Phase Map, 전이 Sankey, Emerging Radar, 조합 네트워크, 분류축 교차(A·B·C), 신흥 기술 탐지(임베딩 — 출원인·기간 선택 가능)</td></tr>' +
      '<tr><td>🎯 White Space &amp; R&amp;D</td><td>Opportunity Matrix(자사=출원인 선택 가능, ◇=자사 역량 보유, 상위 기회 주석 표시), 미점유 조합 UpSet, 문제–해결수단 매트릭스(C축=해결과제 × B축=해결수단 — 두 축 매핑 시 활성), 추천 R&amp;D 테마</td></tr>' +
      '<tr><td colspan="2" style="background:#f4f8fb;font-weight:700">🏢 기업(출원인) 분석 — "이 회사는 무엇을 하는가"</td></tr>' +
      '<tr><td>🏢 기업 분석</td><td>출원인 포커스(집중 기술 + 🆕 신규 진입 기술(최근 N년 내 첫 출원) + ★ 급부상 아이템), 기업 DNA(12지표 계산식 정의표 포함), 기술 궤적, 선도–추종, 권리범위 엔트로피, 출원인·현재권리자 관계(양도 네트워크), 전략 유사도·중첩도, Patent Asset Index(공식 방법론 TR·MC·CI·PAI), Portfolio 종합</td></tr>' +
      '<tr><td>⚖️ Patent Power</td><td>특허 한 건 단위의 힘: 핵심특허 영향력(출원인 선택 가능 — 점수는 전체 기준 유지), 인용 확산, 청구항 밀집도, 발명자 이동, 의미 기반 영향력(임베딩), 권리 중첩 네트워크(임베딩)</td></tr>' +
      '<tr><td colspan="2" style="background:#f4f8fb;font-weight:700">🔎 심층·품질</td></tr>' +
      '<tr><td>🔎 심층 시그널</td><td>잘 안 쓰는 WIPS 필드 기반 신호 6개 탭(모두 출원인 선택 가능): 수명·시장(생존곡선·진입 시차) / 심사 이력(심사관 인용·우선심사·이상탐지) / 출원 행태(대리인·분할·개시 충실도) / 분쟁·국가과제 / 라이선스·표준·양도 / 거절·과학·심사관</td></tr>' +
      '<tr><td>🧪 Data Quality</td><td><b>검증 리포트</b>(엔진 검증 정보·데이터 정합성 셀프 체크·검증 레지스트리), 분류 품질 진단(Confusion Map·응집도), 출원인 표준화 검토</td></tr></tbody></table>' +
      '<div style="color:#647b8d;font-size:11.5px;margin-top:6px">좌측 메뉴는 ① 전체 동향 → ② 기술 분석(어떤 기술) → ③ 기업 분석(어느 회사) → ④ 심층·품질 순서로 배열되어 있습니다 — 전체를 훑고, 기술을 고르고, 회사를 파고드는 흐름입니다.</div>');
    section('🖱️ 차트 공통 기능',
      '<ul style="padding-left:18px;line-height:1.9">' +
      '<li><b>드릴다운</b>: 차트의 점·막대·셀·노드를 클릭하면 근거 특허 목록이 열립니다. 표의 파란 텍스트도 클릭 가능합니다.</li>' +
      '<li><b>👥 출원인 선택</b>: 출원 동향 · 기술분류 동향 · 출원인 포커스 · 신흥 기술 탐지 · 기술×연도 버블 · 심층 시그널 4개 탭 · 특수 신호 2개 탭(심사관 인텔리전스 포함) · 핵심특허 영향력 카드 상단의 드롭다운으로 특정 출원인만 골라 볼 수 있습니다 (공동출원 건 포함 매칭). White Space Map 에서는 선택한 출원인이 <b>자사</b>가 되어 ◇(자사 역량 보유) 판정 기준이 됩니다. 출원인 포커스 탭은 선택한 회사의 집중 기술과 "작지만 최근 3년에 급부상한 아이템"을 찾아줍니다.</li>' +
      '<li><b>Excel</b>: 카드 우상단 Excel 버튼 — 화면 차트의 집계 데이터를 시트별로 다운로드합니다. 첫 시트 "설명"에 카드 설명·각 시트의 축/색 의미·차트 해석·인사이트가 함께 들어가 파일만 열어도 데이터 의미를 알 수 있습니다. 일부 차트는 화면보다 상세한 원천 데이터 시트가 추가로 붙습니다 (예: 기업별 과학 근접도 — 회사별 평균 NPL·표본 수·NPL 인용 특허 수).</li>' +
      '<li><b>PNG/SVG</b>: 보고서용 이미지 저장.</li>' +
      '<li><b>🤖 AI 인사이트 (차트별)</b>: "LLM 인사이트 생성 (차트별)" 버튼은 카드 안의 <b>각 차트마다 개별로</b> 그 차트의 수치·읽는 법을 근거로 <b>IP Landscape 전문 컨설턴트 수준의</b> 슬라이드 형식 인사이트를 만듭니다 — [슬라이드 제목]→[차트 요지](이 차트가 어떤 목적으로 무엇을 보여주는지 한 줄)→[핵심 메시지]→<b>[심층 해석]</b>(경쟁 구도·기술 수명주기 위치·진입장벽·변곡점·R&amp;D 전략 관점, "관찰 수치→해석→함의" 구조)→[근거 데이터]→[시사점·제언](단기/중기 우선순위 + 후속 분석 제안)→[유의사항]. 뻔한 차트 묘사가 아니라 "이 수치가 왜 중요한가"에 집중하며, 화면 데이터가 뒷받침하지 않는 해석은 쓰지 않도록 지시됩니다 (진행 표시 n/m). 각 차트 아래의 "💡 이 차트의 인사이트"는 LLM 없이 항상 표시되는 규칙 기반 요약입니다. AI 패널에서는 추가 질문(챗)이 가능하고 "웹 검색 포함"을 켜면 출처 링크와 함께 외부 검색을 참고합니다.</li>' +
      '<li><b>🗂️ 인사이트 보관함 → PPT</b>: 생성된 인사이트는 차트 이미지와 함께 작업별로 자동 저장됩니다 (기본은 현재 작업만 표시, 이전 작업은 버튼으로 선택). 항목을 골라 PPT 로 내려받으면 <b>1p 표지, 2p 목차, 이후 차트마다 [차트 페이지: 차트 + 바로 아래 "이 차트의 의미" 한 줄 캡션 → 다음 페이지: 나머지 인사이트 전체]</b> 순서로 들어가고, 카드에 차트가 여러 개면 전부 수록됩니다. 인사이트 페이지는 임원 보고용으로 디자인되어 있습니다 — 옅은 카드 패널 배경, ▎섹션 머리글, 핵심 메시지 ■ 네이비 강조 불릿, 시사점 ➤ 화살 불릿, 유의사항 별도 색상, 네이비 표지·페이지 번호 푸터·차트 비율 유지.</li>' +
      '<li><b>💾 분석 스냅샷</b>: Settings 의 "분석 스냅샷" 카드(또는 상단 헤더 저장 버튼)로 현재 분석 상태(Dataset·필터·분석 단위·보던 화면)를 이름 붙여 저장하고, 목록이나 헤더 드롭다운에서 선택해 그대로 복원할 수 있습니다. 데이터가 그대로면 결과는 서버 캐시에서 즉시 열립니다.</li>' +
      '<li><b>👤 내 작업만 보기</b>: 업로드 작업·분석 스냅샷 목록에서 작업자 드롭다운으로 고르거나 이름/팀명을 직접 입력하면 내 작업만 날짜별로 표시됩니다. 이름은 브라우저에 기억되어 다음 방문 때 자동 적용되고, "전체 보기"로 다른 사람 작업도 볼 수 있습니다 (편의 필터 — 접근 차단은 Dataiku 권한으로 관리).</li>' +
      '<li><b>비차단 로딩</b>: 계산이 오래 걸리는 분석은 우하단 배지로 진행 상태만 표시됩니다 — 기다리는 동안 다른 탭을 자유롭게 볼 수 있고, 돌아오면 캐시에서 바로 열립니다.</li>' +
      '<li><b>📑 한 화면 한 차트 (차트 페이저)</b>: 카드에 차트가 여러 개면 상단 페이저(◀ 이전 / 목록 선택 / 다음 ▶)로 <b>한 번에 한 차트씩</b> 크게 봅니다. 스크롤로 길게 나열되지 않아 각 차트에 집중할 수 있고, 예전처럼 세로로 모두 펼치려면 "전체 보기"를 켜세요 (선택은 브라우저에 기억됩니다). 차트 해석·인사이트·AI 패널은 페이지와 무관하게 항상 하단에 표시됩니다.</li>' +
      '<li><b>📖 차트 해석</b>: 각 차트 아래 회색 박스에 축 의미와 읽는 법이 항상 표시됩니다.</li>' +
      '<li><b>🖱️ 휠 스크롤 보호</b>: 차트 영역은 흐린 테두리로 구분되어 있고, 차트 위에서 마우스 휠을 굴려도 차트가 확대/축소되지 않습니다 (페이지 스크롤만 동작). 확대가 필요하면 차트 우상단 도구 모음의 줌 버튼을 사용하세요.</li>' +
      '<li><b>🤝 공동출원 처리</b>: 출원인별 차트(순위·매트릭스·버블)는 Settings → 분석 설정의 "공동출원 집계"를 따릅니다 — 기본 "각각 집계"는 공동출원 1건을 각 공동출원인에게 1건씩 세고(합계가 전체 건수를 넘을 수 있음, 차트 아래에 안내 표시), "대표 출원인만"은 첫 출원인에게만 셉니다. 출원 동향·기술분류 동향·신흥 기술 탐지의 <b>출원인 선택</b>과 기업 필터는 어느 모드에서든 공동출원 건을 포함해 그 회사 문헌을 찾습니다. 협력 네트워크·공동출원 비율 등 공동출원 자체 분석은 이 설정과 무관합니다.</li></ul>');
    section('✅ 검증 체계 — 이 앱의 수치를 신뢰할 수 있는 이유',
      '<ul style="padding-left:18px;line-height:1.9">' +
      '<li><b>검증 리포트 (Data Quality 첫 탭)</b>: 이 앱이 어떻게 검증되었는지가 화면에 그대로 공개됩니다. 표시되는 수치는 전부 실측입니다 — 자동 테스트 수는 빌드 시 저장소에서 직접 센 값이고, 셀프 체크는 지금 로딩된 데이터로 즉석에서 다시 계산한 값입니다.</li>' +
      '<li><b>독립 재계산 검증</b>: 생존곡선(Kaplan-Meier)은 손계산 표본과, 기술 DNA 각 축은 공개된 정의표와, 차트 집계는 원본 데이터 수동 집계와 대조하는 테스트가 저장소에 남아 있습니다 (검증 리포트의 레지스트리에서 테스트 파일::함수 이름 확인 가능).</li>' +
      '<li><b>함정 회귀 테스트</b>: 공동출원 중복 카운팅, 발명자 이동 오인, 법인 접미사 오분리, 역상관의 선행신호 오인, 실무 파일 결측(NaN) 왜곡 등 실제로 발견해 수정한 버그마다 재발 방지 테스트가 추가되어 있습니다.</li>' +
      '<li><b>데이터 정합성 셀프 체크</b>: KPI ↔ 연도별 차트 합, 날짜 논리(등록일 ≥ 출원일), 미래 연도 이상치, 문헌번호 중복, 기술분류 계층 정합 등을 업로드된 데이터로 즉석 점검합니다. 컬럼이 매핑되지 않아 점검할 수 없는 항목은 <b>"확인 불가"로 정직하게 표시</b>되며 통과로 위장하지 않습니다.</li>' +
      '<li><b>정직성 원칙</b>: 계산 불가는 이유와 함께 표시, 표본 부족은 경고 표시, 모든 점수의 계산식은 화면 공개, 모든 집계는 드릴다운으로 근거 특허까지 추적 가능합니다.</li></ul>');
    section('🧠 임베딩·군집·LLM 안내',
      '<ul style="padding-left:18px;line-height:1.9">' +
      '<li><b>임베딩 모델</b>: 사내 서버의 로컬 KR-SBERT 특허 특화 모델을 사용합니다 (네트워크 비용 없음). 실제 사용 방식은 각 카드 하단 "방법: 임베딩 adapter:sbert" 로 확인할 수 있으며, 모델 미가용 시 TF-IDF 폴백이 명시됩니다.</li>' +
      '<li><b>임베딩 벡터 파일 업로드 (.npy/.npz)</b>: 미리 계산한 벡터가 있으면 Settings → "🧬 임베딩 벡터 파일" 카드에서 파일로 올려 사용할 수 있습니다 (raw Excel 에 벡터 컬럼을 넣을 필요 없음). 권장은 <b>.npz(embeddings + ids)</b> 형식이며 ids 는 출원번호(또는 공개번호) — 하이픈·공백 형식 차이는 자동 흡수됩니다. "매칭 진단"으로 현재 데이터와 몇 건이 연결되는지 먼저 확인하고 "사용"을 누르면 모든 임베딩 분석이 이 벡터를 사용합니다. 매칭 안 된 문헌은 제외될 뿐 임의 벡터를 만들지 않습니다.</li>' +
      '<li><b>임베딩 대상</b>: 청구항 분석(밀집도·청구구조 다양성)=독립청구항 / 주제 분석(신흥 탐지·의미 영향력·중첩 네트워크)=명칭+요약(부족 시 독립청구항) / 문제–해결수단 의미 그룹=과제·수단 문구.</li>' +
      '<li><b>군집화</b>: 밀집도=HDBSCAN(자동), 신흥 탐지=KMeans(k 자동), 의미 그룹=계층 군집(거리 임계값 ps_group_distance 로 조정). 모든 시드는 고정되어 같은 데이터에서 같은 결과가 나옵니다.</li>' +
      '<li><b>LLM</b>: 허용 목록의 사내 모델만 사용하고, 특허 원문이 아닌 화면 집계값·요약 통계만 전달합니다.</li></ul>');
    section('🔐 로그인·권한',
      '<ul style="padding-left:18px;line-height:1.9">' +
      '<li><b>로그인</b>: ID=팀명/이름, 비밀번호=사원번호. 처음 로그인하면 자동 등록되고, <b>첫 번째 등록 사용자가 관리자</b>가 됩니다. 사원번호는 해시로만 저장됩니다.</li>' +
      '<li><b>권한</b>: 일반 사용자는 <b>본인이 올린 업로드 작업·스냅샷·인사이트만</b> 보이고 삭제할 수 있습니다. 관리자는 전체를 보고 Settings 의 "사용자 관리"에서 관리자 지정/해제·사용자 삭제를 할 수 있습니다. 로그인 도입 전에 만들어진(소유자 없는) 항목은 모두에게 보입니다.</li>' +
      '<li><b>보안 성격</b>: 이 로그인은 작업 구분용 편의 접근 관리입니다 — 사원번호는 추측 가능성이 있는 약한 비밀번호이며, 강한 접근 통제가 필요하면 Dataiku 프로젝트 권한을 사용하세요.</li></ul>');
    section('❓ 자주 묻는 문제',
      '<table class="ipls-table"><thead><tr><th>증상</th><th>확인 사항</th></tr></thead><tbody>' +
      '<tr><td>분석이 "비활성화"로 표시됨</td><td>Settings → 컬럼 매핑에서 안내된 필수 컬럼을 매핑하세요. \'등록일[KR,JP,…]\' 처럼 국가목록이 붙은 WIPS 헤더와 \'(B1)\' 류 코드는 자동 인식됩니다. 매핑했는데도 안 되면 메시지의 [매핑 진단]과 "예시 값"으로 실제 값 형식을 확인하세요.</td></tr>' +
      '<tr><td>일부 섹션만 생략됨</td><td>심층 시그널·심화 분석·경영 차트는 섹션별 필요 컬럼이 달라, 있는 데이터만 계산하고 "어느 섹션: 어떤 컬럼 필요"를 표시합니다. 일부는 대체 계산을 합니다 (예: 소멸일이 없으면 법적상태×존속기간(예상)만료일로 생존곡선 근사).</td></tr>' +
      '<tr><td>생존곡선이 100% 평행선으로만 보임</td><td>등록일만 있으면 곡선은 항상 그려지며, 소멸(포기) 이벤트가 0건이면 전 특허가 관측 지속으로 처리되어 평행선이 됩니다 — 포트폴리오가 아직 젊거나 소멸 정보가 데이터에 없는 경우입니다. 소멸일(또는 법적상태+존속기간(예상)만료일)을 매핑하면 실제 소멸 시점이 반영됩니다 (차트 노트에 기준이 명시됩니다).</td></tr>' +
      '<tr><td>White Space 의 ◇(자사 역량)가 안 보임</td><td>카드 상단 "자사(출원인) 선택"에서 자사로 볼 회사를 고르거나, \'자사 특허 여부\' 컬럼을 매핑하세요. 둘 다 없으면 ◇ 표시는 꺼진 상태이며 인사이트에 안내가 나옵니다.</td></tr>' +
      '<tr><td>과학 근접도 막대를 클릭하면 어떤 특허가 나오나요</td><td>그 회사(공동출원 포함)의 특허 중 <b>NPL(비특허문헌)을 1건 이상 인용한 특허만</b> 열립니다 — 평균값의 실제 근거를 바로 검증하기 위한 동작입니다. 기술분류 막대도 같은 방식입니다.</td></tr>' +
      '<tr><td>필터에 이상한 값이 보임</td><td>Settings → 출원인 표준화에서 병합 규칙을 승인하거나, 컬럼 매핑에서 해당 개념의 매핑 컬럼을 바꾸세요.</td></tr>' +
      '<tr><td>연도가 최근에 급감해 보임</td><td>최근 1~2년은 미공개 출원 때문에 실제보다 낮게 보입니다 (하락으로 단정 금지).</td></tr>' +
      '<tr><td>지정국 진입 시차가 생략됨</td><td>분석 단위를 "문헌"으로 바꾸세요 (패밀리 대표 단위에서는 구성 문헌이 제거됩니다).</td></tr>' +
      '<tr><td>의미 그룹이 너무 크게/작게 묶임</td><td>Settings → 임계값 ps_group_distance 를 조정하세요 (낮추면 엄격, 높이면 느슨).</td></tr>' +
      '<tr><td>문제–해결수단 매트릭스가 비활성</td><td>C축(해결과제)·B축(해결수단) 기술분류가 모두 매핑된 경우에만 그려집니다. Settings → 컬럼 매핑에서 두 축을 확인하세요.</td></tr>' +
      '<tr><td>Market Coverage 가 모든 기업 동일</td><td>전 문헌이 단일국(KR) 패밀리면 정상입니다 — 차트 제목의 기준 문구를 확인하세요. \'한국-1 | 미국-0\' 형식에서 건수 0 국가는 보호국에서 제외됩니다.</td></tr></tbody></table>' +
      '<div class="disclaimer">본 앱의 모든 지표는 통계적 신호이며 법률 자문(FTO·유효성 판단)을 대체하지 않습니다.</div>');
  };

  Views.settings = function (content) {
    var grid = Ui.el('<div class="settings-grid"></div>');
    content.appendChild(grid);
    var s = (State.config && State.config.settings) || {};

    /* 엑셀 업로드 작업 저장소 */
    var cu = card('📤 엑셀 업로드 (작업 저장소)',
      'WIPS Excel(xlsx/xls/csv)을 앱에서 직접 올려 바로 분석합니다. 작업자 이름과 작업명은 필수이며, ' +
      '업로드한 파일은 서버 저장소에 보관되어 아래 목록에서 언제든 다시 불러올 수 있습니다 ' +
      '(Backend 재시작 후에도 유지). 파일 60MB · 60,000행 이하, 첫 시트만 사용합니다. ' +
      '아래 "내 작업 보기"에 이름/팀명을 입력하면 내가 올린 작업만 날짜별로 표시됩니다.');
    grid.appendChild(cu.root);
    var upForm = Ui.el('<div>' +
      '<div class="settings-row"><label>작업자 이름 *</label>' +
      '<input type="text" id="up-worker" maxlength="60" placeholder="예: 홍길동" style="flex:1"></div>' +
      '<div class="settings-row"><label>작업명 *</label>' +
      '<input type="text" id="up-job" maxlength="120" placeholder="예: 2026 상반기 패키징 IP 조사" style="flex:1"></div>' +
      '<div class="settings-row"><label>엑셀 파일 *</label>' +
      '<input type="file" id="up-file" accept=".xlsx,.xls,.csv" style="flex:1"></div>' +
      '</div>');
    cu.body.appendChild(upForm);
    var upBtn = Ui.el('<button class="btn small primary">업로드 → 저장하고 분석 시작</button>');
    cu.body.appendChild(upBtn);
    var upFilt = Ui.el('<div class="settings-row" style="margin-top:12px">' +
      '<label>내 작업 보기</label>' +
      '<select id="up-worker-sel" style="max-width:170px"><option value="">작업자 선택…</option></select>' +
      '<input type="text" id="up-filter" maxlength="60" ' +
      'placeholder="또는 이름/팀명 직접 입력" style="flex:1">' +
      '<label style="display:flex;align-items:center;gap:4px;font-size:12px;white-space:nowrap;cursor:pointer">' +
      '<input type="checkbox" id="up-showall">전체 보기</label></div>');
    cu.body.appendChild(upFilt);
    var listWrap = Ui.el('<div style="margin-top:8px"></div>');
    cu.body.appendChild(listWrap);
    upForm.querySelector('#up-worker').value = getWorkerName();
    upFilt.querySelector('#up-filter').value = getWorkerName();

    function useDataset(name) {
      return Api.post('/api/settings', { dataset: name }).then(function (resp) {
        State.config.settings = resp.settings;
        Ui.toast('분석 Dataset 이 "' + name + '" 로 설정되었습니다. 컬럼 매핑을 확인하세요.');
        if (!resp.settings.analysis_purpose) {
          // 분석 시작 전 목적 선택 유도 — 목적별 추천 차트 우선 표시
          State.view = 'purpose';
          Ui.toast('분석 목적을 선택하면 목적에 맞는 차트를 추천해 드립니다.');
        }
        boot(true);
      }).catch(errToast);
    }

    var upItems = [];
    function renderUploadList() {
      listWrap.innerHTML = '';
      var q = upFilt.querySelector('#up-filter').value.trim();
      var showAll = upFilt.querySelector('#up-showall').checked;
      var filtered = (showAll || !q) ? upItems
        : upItems.filter(function (it) { return workerMatches(it.worker, q); });
      var head = (showAll || !q)
        ? '💾 저장된 업로드 작업 — 전체 ' + upItems.length + '건'
        : '💾 "' + Ui.esc(q) + '" 작업 ' + filtered.length + '건 / 전체 ' + upItems.length + '건';
      listWrap.appendChild(Ui.el('<div style="font-weight:700;font-size:12.5px;margin-bottom:4px">' +
        head + '</div>'));
      if (!filtered.length) {
        listWrap.appendChild(Ui.el('<div class="status-empty">' +
          (upItems.length && q && !showAll
            ? '"' + Ui.esc(q) + '" 작업자/팀의 저장된 작업이 없습니다. ' +
              '"전체 보기"를 켜면 다른 작업자의 작업도 볼 수 있습니다.'
            : '저장된 작업이 없습니다.') + '</div>'));
        return;
      }
      var sorted = filtered.slice().sort(function (a, b) {
        return String(b.uploaded_at || '').localeCompare(String(a.uploaded_at || ''));
      });
      var lastDate = null;
      var rows = [];
      sorted.forEach(function (it) {
        var dstr = String(it.uploaded_at || '').slice(0, 10) || '날짜 미상';
        if (dstr !== lastDate) {
          lastDate = dstr;
          var nDay = sorted.filter(function (x) {
            return (String(x.uploaded_at || '').slice(0, 10) || '날짜 미상') === dstr;
          }).length;
          var sep = document.createElement('tr');
          sep.innerHTML = '<td colspan="6" style="background:#eef5fa;font-weight:700;' +
            'font-size:11.5px;color:#4a6274">📅 ' + Ui.esc(dstr) + ' (' + nDay + '건)</td>';
          rows.push(sep);
        }
        var tr = document.createElement('tr');
          tr.insertAdjacentHTML('beforeend',
            '<td><b>' + Ui.esc(it.job) + '</b><br><span style="color:#93a5b4;font-size:10.5px">' +
            Ui.esc(it.orig_filename) + '</span></td>' +
            '<td>' + Ui.esc(it.worker) + '</td>' +
            '<td style="white-space:nowrap">' + Ui.esc(it.uploaded_at) + '</td>' +
            '<td class="num">' + Ui.num(it.n_rows, 0) + '행</td>' +
            '<td>' + (it.loaded ? '<span class="badge good">로드됨</span>' :
              (it.file_exists ? '' : '<span class="badge warn">파일 없음</span>')) + '</td>');
          var tdAct = document.createElement('td');
          tdAct.style.whiteSpace = 'nowrap';
          var loadBtn = Ui.el('<button class="btn small">불러와 분석</button>');
          loadBtn.disabled = !it.file_exists;
          loadBtn.addEventListener('click', function () {
            Api.post('/api/uploads/load', { id: it.id }, '저장 파일 불러오는 중…')
              .then(function (r) { return useDataset(r.entry.dataset); })
              .catch(errToast);
          });
          tdAct.appendChild(loadBtn);
          var delBtn = Ui.el('<button class="btn small" style="margin-left:4px">삭제</button>');
          delBtn.addEventListener('click', function () {
            if (!window.confirm('"' + it.job + '" (' + it.worker + ') 작업을 삭제할까요? 저장 파일도 함께 지워집니다.')) return;
            Api.post('/api/uploads/delete', { id: it.id }).then(function () {
              Ui.toast('삭제되었습니다.');
              renderUploads();
            }).catch(errToast);
          });
          tdAct.appendChild(delBtn);
          tr.appendChild(tdAct);
          rows.push(tr);
        });
      var tbl = Ui.el(simpleTable(['작업명 / 파일', '작업자', '업로드 시각', '행수', '상태', ''], []));
      rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
      var wrap = Ui.el('<div style="overflow-x:auto;max-height:280px;overflow-y:auto"></div>');
      wrap.appendChild(tbl);
      listWrap.appendChild(wrap);
    }
    /* 작업자 선택 드롭다운 — 업로드·스냅샷에 등장하는 작업자/팀명을 모아 보여줘
       이름을 몰라도 골라서 필터링할 수 있게 한다. */
    function workerNames() {
      var names = {};
      (upItems || []).forEach(function (it) {
        var w = String(it.worker || '').trim();
        if (w) names[w] = 1;
      });
      (snapItems || []).forEach(function (p) {
        var w = String(p.worker || '').trim();
        if (w) names[w] = 1;
      });
      return Object.keys(names).sort();
    }
    function refreshWorkerSelects() {
      [upFilt.querySelector('#up-worker-sel'),
       (typeof snapFilt !== 'undefined' && snapFilt) ? snapFilt.querySelector('#snap-worker-sel') : null]
        .forEach(function (sel) {
          if (!sel) return;
          var cur = sel.value;
          sel.innerHTML = '<option value="">작업자 선택…</option>';
          workerNames().forEach(function (w) {
            var o = document.createElement('option');
            o.value = w; o.textContent = w;
            sel.appendChild(o);
          });
          sel.value = cur;
        });
    }
    function renderUploads() {
      Api.get('/api/uploads').then(function (d) {
        upItems = d.items || [];
        refreshWorkerSelects();
        renderUploadList();
      }).catch(errToast);
    }
    upFilt.querySelector('#up-filter').addEventListener('input', function (ev) {
      setWorkerName(ev.target.value);
      renderUploadList();
    });
    upFilt.querySelector('#up-worker-sel').addEventListener('change', function (ev) {
      upFilt.querySelector('#up-filter').value = ev.target.value;
      setWorkerName(ev.target.value);
      renderUploadList();
    });
    upFilt.querySelector('#up-showall').addEventListener('change', renderUploadList);
    upBtn.addEventListener('click', function () {
      var worker = document.getElementById('up-worker').value.trim();
      var job = document.getElementById('up-job').value.trim();
      var fileEl = document.getElementById('up-file');
      if (!worker || !job) { Ui.toast('작업자 이름과 작업명을 반드시 입력하세요.', 'error'); return; }
      if (!fileEl.files || !fileEl.files[0]) { Ui.toast('엑셀 파일을 선택하세요.', 'error'); return; }
      setWorkerName(worker);
      upFilt.querySelector('#up-filter').value = worker;
      var fd = new FormData();
      fd.append('file', fileEl.files[0]);
      fd.append('worker', worker);
      fd.append('job', job);
      upBtn.disabled = true;
      Api.upload('/api/uploads', fd, '엑셀 업로드·저장 중…').then(function (r) {
        Ui.toast('업로드 완료: ' + r.entry.n_rows + '행 저장됨.');
        fileEl.value = '';
        renderUploads();
        return useDataset(r.entry.dataset);
      }).catch(errToast).finally(function () { upBtn.disabled = false; });
    });
    renderUploads();

    /* 임베딩 벡터 파일 (.npy/.npz) 업로드·선택 */
    var ce = card('🧬 임베딩 벡터 파일 (.npy/.npz)',
      '사전 계산한 임베딩 벡터를 raw Excel 컬럼 대신 별도 파일로 올려 사용합니다. ' +
      '권장 형식: .npz — embeddings(N×D 벡터) + ids(출원번호 또는 공개번호) 두 배열. ' +
      '키가 없는 .npy(N×D)는 현재 dataset 과 행 수가 정확히 일치할 때만 행 순서로 매칭됩니다. ' +
      '매칭은 출원번호/공개번호 기준이며 하이픈·공백 등 형식 차이는 자동 흡수, ' +
      '매칭 안 된 문헌은 임베딩 분석에서 제외됩니다 (임의 벡터 생성 없음). ' +
      '파일을 "사용"으로 지정하면 모든 임베딩 분석(신흥 탐지·의미 영향력·유사도 네트워크 등)이 ' +
      '이 벡터를 사용하고, 해제하면 기존 방식(컬럼/KR-SBERT)으로 돌아갑니다.');
    grid.appendChild(ce.root);
    var embForm = Ui.el('<div class="settings-row"><label>벡터 파일 *</label>' +
      '<input type="file" id="emb-file" accept=".npy,.npz" style="flex:1"></div>');
    ce.body.appendChild(embForm);
    var embBtn = Ui.el('<button class="btn small primary">업로드</button>');
    ce.body.appendChild(embBtn);
    var embList = Ui.el('<div style="margin-top:10px"></div>');
    ce.body.appendChild(embList);

    function renderEmbeddings() {
      Api.get('/api/embeddings').then(function (r) {
        embList.innerHTML = '';
        var items = r.items || [];
        if (!items.length) {
          embList.appendChild(Ui.el('<div style="color:#8aa0b2;font-size:12px">' +
            '업로드된 임베딩 파일이 없습니다.</div>'));
          return;
        }
        items.forEach(function (it) {
          var selected = r.selected === it.id;
          var row = Ui.el('<div class="settings-row" style="align-items:center">' +
            '<div style="flex:1;min-width:0"><b style="font-size:12.5px">' + Ui.esc(it.filename) +
            (selected ? ' <span class="badge good">사용 중</span>' : '') + '</b>' +
            '<div style="color:#8aa0b2;font-size:11px">' + it.n + '건 × ' + it.dim + '차원 · ' +
            (it.has_ids ? '키(출원번호) 포함' : '키 없음(행 순서 매칭)') + ' · ' +
            Ui.esc(it.created_at || '') + (it.owner ? ' · ' + Ui.esc(it.owner) : '') +
            '</div><div class="emb-match" style="color:#46607a;font-size:11px"></div></div>' +
            '<button class="btn small" data-act="match">매칭 진단</button>' +
            '<button class="btn small ' + (selected ? '' : 'primary') + '" data-act="sel">' +
            (selected ? '사용 해제' : '사용') + '</button>' +
            '<button class="btn small" data-act="del">삭제</button></div>');
          row.querySelector('[data-act="match"]').addEventListener('click', function () {
            Api.post('/api/embeddings/match', { id: it.id }, '매칭 진단 중…').then(function (m) {
              row.querySelector('.emb-match').textContent =
                '매칭: ' + m.matched + ' / ' + m.n_data + '건 (' + m.match_field + ' 기준' +
                (m.mode === 'order' ? ', 행 순서' : '') + ')' + (m.note ? ' — ' + m.note : '');
            }).catch(errToast);
          });
          row.querySelector('[data-act="sel"]').addEventListener('click', function () {
            Api.post('/api/embeddings/select', { id: selected ? null : it.id })
              .then(function () {
                Ui.toast(selected ? '임베딩 파일 사용을 해제했습니다.'
                                  : '이제 임베딩 분석이 이 파일의 벡터를 사용합니다.');
                renderEmbeddings();
              }).catch(errToast);
          });
          row.querySelector('[data-act="del"]').addEventListener('click', function () {
            if (!confirm('임베딩 파일을 삭제할까요?')) return;
            Api.post('/api/embeddings/delete', { id: it.id })
              .then(renderEmbeddings).catch(errToast);
          });
          embList.appendChild(row);
        });
      }).catch(function (e) {
        // 구버전 백엔드(엔드포인트 없음=404)만 조용히 무시 — 그 외 오류는
        // 표시해야 "파일이 없는 것"과 "목록 로드 실패"를 구분할 수 있다
        var msg = String((e && e.message) || '');
        if (msg.indexOf('404') === -1 && msg.indexOf('LookupError') === -1) {
          Ui.toast('임베딩 파일 목록을 불러오지 못했습니다: ' + msg);
        }
      });
    }
    embBtn.addEventListener('click', function () {
      var fileEl = embForm.querySelector('#emb-file');
      if (!fileEl.files.length) { Ui.toast('.npy 또는 .npz 파일을 선택하세요.'); return; }
      var fd = new FormData();
      fd.append('file', fileEl.files[0]);
      embBtn.disabled = true;
      Api.upload('/api/embeddings', fd, '임베딩 파일 업로드 중…').then(function (r) {
        Ui.toast('업로드 완료: ' + r.entry.n + '건 × ' + r.entry.dim + '차원.');
        fileEl.value = '';
        renderEmbeddings();
      }).catch(errToast).finally(function () { embBtn.disabled = false; });
    });
    renderEmbeddings();

    /* 분석 스냅샷 저장·불러오기 */
    var cs = card('💾 분석 스냅샷 — 기존 분석 결과 불러오기',
      '현재 분석 상태(Dataset·필터·분석 단위·보고 있던 화면)를 이름을 붙여 저장하고, 목록에서 ' +
      '선택해 그대로 복원합니다. 데이터가 바뀌지 않았다면 분석 결과는 서버 캐시에서 즉시 열립니다. ' +
      '저장 시 위 "내 작업 보기"에 입력한 작업자/팀명이 함께 기록되어, 내가 저장한 스냅샷만 ' +
      '날짜별로 골라볼 수 있습니다. 상단 헤더의 "저장된 분석…" 드롭다운에서도 바로 불러올 수 있습니다.');
    grid.appendChild(cs.root);
    var snapForm = Ui.el('<div class="settings-row">' +
      '<input type="text" id="snap-name" maxlength="60" placeholder="스냅샷 이름 *" style="flex:1">' +
      '<input type="text" id="snap-note" maxlength="200" placeholder="메모 (선택)" style="flex:2"></div>');
    cs.body.appendChild(snapForm);
    var snapSave = Ui.el('<button class="btn small primary">현재 분석 상태 저장</button>');
    cs.body.appendChild(snapSave);
    var snapFilt = Ui.el('<div class="settings-row" style="margin-top:10px">' +
      '<label>내 스냅샷 보기</label>' +
      '<select id="snap-worker-sel" style="max-width:170px"><option value="">작업자 선택…</option></select>' +
      '<input type="text" id="snap-filter" maxlength="60" ' +
      'placeholder="또는 이름/팀명 직접 입력" style="flex:1">' +
      '<label style="display:flex;align-items:center;gap:4px;font-size:12px;white-space:nowrap;cursor:pointer">' +
      '<input type="checkbox" id="snap-showall">전체 보기</label></div>');
    cs.body.appendChild(snapFilt);
    var snapList = Ui.el('<div style="margin-top:8px"></div>');
    cs.body.appendChild(snapList);
    snapFilt.querySelector('#snap-filter').value = getWorkerName();

    var snapItems = [];
    function renderSnapList() {
      snapList.innerHTML = '';
      var q = snapFilt.querySelector('#snap-filter').value.trim();
      var showAll = snapFilt.querySelector('#snap-showall').checked;
      if (!snapItems.length) {
        snapList.innerHTML = '<div class="status-empty">저장된 분석 스냅샷이 없습니다.</div>';
        return;
      }
      var filtered = (showAll || !q) ? snapItems
        : snapItems.filter(function (p) { return workerMatches(p.worker, q); });
      if (!filtered.length) {
        var nOld = snapItems.filter(function (p) { return !String(p.worker || '').trim(); }).length;
        snapList.innerHTML = '<div class="status-empty">"' + Ui.esc(q) +
          '" 작업자/팀의 스냅샷이 없습니다.' +
          (nOld ? ' 작업자 미지정(예전에 저장된) 스냅샷 ' + nOld +
            '건은 "전체 보기"에서 확인할 수 있습니다.' : '') + '</div>';
        return;
      }
      var sorted = filtered.slice().sort(function (a, b) {
        return String(b.saved_at || '').localeCompare(String(a.saved_at || ''));
      });
      var rows = [];
      var lastDate = null;
      sorted.forEach(function (p) {
        var dstr = String(p.saved_at || '').slice(0, 10) || '날짜 미상';
        if (dstr !== lastDate) {
          lastDate = dstr;
          var nDay = sorted.filter(function (x) {
            return (String(x.saved_at || '').slice(0, 10) || '날짜 미상') === dstr;
          }).length;
          var sep = document.createElement('tr');
          sep.innerHTML = '<td colspan="5" style="background:#eef5fa;font-weight:700;' +
            'font-size:11.5px;color:#4a6274">📅 ' + Ui.esc(dstr) + ' (' + nDay + '건)</td>';
          rows.push(sep);
        }
        var tr = document.createElement('tr');
        var td0 = document.createElement('td');
        var b = Ui.el('<span class="clickable"><b>' + Ui.esc(p.name) + '</b></span>');
        b.addEventListener('click', function () { loadSnapshot(p.name).catch(errToast); });
        td0.appendChild(b);
        tr.appendChild(td0);
        tr.insertAdjacentHTML('beforeend',
          '<td>' + Ui.esc(p.worker || '-') + '</td>' +
          '<td style="white-space:nowrap">' + Ui.esc(p.saved_at || '') + '</td>' +
          '<td>' + Ui.esc(p.note || '') + '</td>');
        var tdAct = document.createElement('td');
        tdAct.style.whiteSpace = 'nowrap';
        var loadBtn = Ui.el('<button class="btn small">불러오기</button>');
        loadBtn.addEventListener('click', function () { loadSnapshot(p.name).catch(errToast); });
        tdAct.appendChild(loadBtn);
        var delBtn = Ui.el('<button class="btn small" style="margin-left:4px">삭제</button>');
        delBtn.addEventListener('click', function () {
          if (!window.confirm("스냅샷 '" + p.name + "' 을(를) 삭제할까요?")) return;
          Api.post('/api/project/load', { name: p.name, delete: true }).then(function () {
            Ui.toast('삭제되었습니다.');
            renderSnapshots(); refreshProjects();
          }).catch(errToast);
        });
        tdAct.appendChild(delBtn);
        tr.appendChild(tdAct);
        rows.push(tr);
      });
      var tbl = Ui.el(simpleTable(['이름', '작업자', '저장 시각', '메모', ''], []));
      rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
      var wrap = Ui.el('<div style="overflow-x:auto;max-height:260px;overflow-y:auto"></div>');
      wrap.appendChild(tbl);
      snapList.appendChild(wrap);
    }
    function renderSnapshots() {
      Api.post('/api/project/load', {}).then(function (d) {
        snapItems = d.projects || [];
        refreshWorkerSelects();
        renderSnapList();
      }).catch(errToast);
    }
    snapFilt.querySelector('#snap-filter').addEventListener('input', function (ev) {
      setWorkerName(ev.target.value);
      renderSnapList();
    });
    snapFilt.querySelector('#snap-worker-sel').addEventListener('change', function (ev) {
      snapFilt.querySelector('#snap-filter').value = ev.target.value;
      setWorkerName(ev.target.value);
      renderSnapList();
    });
    snapFilt.querySelector('#snap-showall').addEventListener('change', renderSnapList);
    snapSave.addEventListener('click', function () {
      var name = document.getElementById('snap-name').value.trim();
      if (!name) { Ui.toast('스냅샷 이름을 입력하세요.', 'error'); return; }
      saveSnapshot(name, document.getElementById('snap-note').value.trim())
        .then(function () {
          document.getElementById('snap-name').value = '';
          renderSnapshots();
        }).catch(errToast);
    });
    renderSnapshots();

    /* 사용자 관리 (관리자 전용) */
    if (Auth.isAdmin()) {
      var cua = card('👥 사용자 관리 (관리자)',
        '등록된 접속자 목록입니다. 관리자는 모든 사용자의 작업·스냅샷·인사이트를 볼 수 있고, ' +
        '일반 사용자는 본인 것만 봅니다. 사용자를 삭제해도 그가 올린 데이터는 남습니다 ' +
        '(소유자 표시만 유지). 마지막 관리자는 해제/삭제할 수 없습니다.');
      grid.appendChild(cua.root);
      var uaList = Ui.el('<div></div>');
      cua.body.appendChild(uaList);
      function renderUsers() {
        Api.get('/api/auth/users').then(function (d) {
          uaList.innerHTML = '';
          var rows = (d.users || []).map(function (u) {
            var tr = document.createElement('tr');
            tr.insertAdjacentHTML('beforeend',
              '<td><b>' + Ui.esc(u.name) + '</b>' +
              (u.name === Auth.user() ? ' <span class="badge">나</span>' : '') + '</td>' +
              '<td>' + (u.is_admin ? '<span class="badge good">관리자</span>' : '일반') + '</td>' +
              '<td style="white-space:nowrap">' + Ui.esc(u.created_at || '') + '</td>' +
              '<td style="white-space:nowrap">' + Ui.esc(u.last_login || '') + '</td>');
            var td = document.createElement('td');
            td.style.whiteSpace = 'nowrap';
            var admBtn = Ui.el('<button class="btn small">' +
              (u.is_admin ? '관리자 해제' : '관리자 지정') + '</button>');
            admBtn.addEventListener('click', function () {
              Api.post('/api/auth/users', { name: u.name, set_admin: !u.is_admin })
                .then(renderUsers).catch(errToast);
            });
            td.appendChild(admBtn);
            var delBtn = Ui.el('<button class="btn small" style="margin-left:4px">삭제</button>');
            delBtn.addEventListener('click', function () {
              if (!window.confirm("사용자 '" + u.name + "' 을(를) 삭제할까요? (데이터는 유지)")) return;
              Api.post('/api/auth/users', { name: u.name, delete: true })
                .then(renderUsers).catch(errToast);
            });
            td.appendChild(delBtn);
            tr.appendChild(td);
            return tr;
          });
          var tbl = Ui.el(simpleTable(['사용자', '권한', '등록일', '최근 로그인', ''], []));
          rows.forEach(function (tr) { tbl.querySelector('tbody').appendChild(tr); });
          var wrap = Ui.el('<div style="overflow-x:auto;max-height:260px;overflow-y:auto"></div>');
          wrap.appendChild(tbl);
          uaList.appendChild(wrap);
        }).catch(errToast);
      }
      renderUsers();
    }

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
        renderPurposeChip();
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
    c1.body.appendChild(selRow('분석 목적', 'analysis_purpose',
      [{ v: '', l: '(선택 안 함)' }].concat(PURPOSES.map(function (p) {
        return { v: p.key, l: p.icon + ' ' + p.label + ' — ' + p.desc };
      })), s.analysis_purpose || ''));
    c1.body.appendChild(Ui.el('<div style="color:#647b8d;font-size:11.5px;margin:-4px 0 8px">' +
      '목적을 선택하면 좌측 <b>🎯 목적 맞춤 분석</b> 메뉴에 목적별 추천 차트가 우선순위와 함께 ' +
      '표시됩니다. 분석 결과 값 자체는 목적과 무관하게 동일합니다.</div>'));
    c1.body.appendChild(selRow('분석 단위', 'analysis_unit',
      [{ v: 'family', l: '패밀리 (기본)' }, { v: 'publication', l: '공개' },
       { v: 'application', l: '출원' }, { v: 'registration', l: '등록' }],
      s.analysis_unit, { reload: true }));
    c1.body.appendChild(selRow('다중분류 처리', 'multiclass_mode',
      [{ v: 'duplicate', l: '중복 계산 (각 분류 1건)' }, { v: 'fractional', l: '1/N 가중' },
       { v: 'primary', l: '대표 분류만' }, { v: 'level_separate', l: '레벨별 집계' }],
      s.multiclass_mode, { reload: true }));
    c1.body.appendChild(selRow('공동출원 집계', 'coapplicant_mode',
      [{ v: 'all', l: '공동출원인 각각 집계 (WIPS 방식, 기본)' },
       { v: 'first', l: '대표(첫) 출원인만' }],
      s.coapplicant_mode || 'all', { reload: true }));
    c1.body.appendChild(Ui.el('<div style="color:#647b8d;font-size:11.5px;margin:-4px 0 8px">' +
      '공동출원 집계는 출원인 순위·매트릭스·버블 등 <b>출원인별 차트</b>에만 적용됩니다. ' +
      '\'각각 집계\'는 공동출원 1건을 각 공동출원인에게 1건씩 세므로 합계가 전체 건수를 ' +
      '넘을 수 있습니다. 협력 네트워크·공동출원 비율 등 공동출원 자체를 분석하는 화면은 ' +
      '이 설정과 무관하게 원본 그대로 계산됩니다. 분석 시작 전에 설정하세요.</div>'));
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
    var emb = s.embedding_adapter || { type: 'sbert' };
    var embSel = Ui.el('<select>' +
      '<option value="sbert">KR-SBERT 로컬 모델 (기본 — snunlp 특허 특화)</option>' +
      '<option value="llm_mesh">LLM Mesh 임베딩 모델</option>' +
      '<option value="dataset">사전 계산 벡터 Dataset</option>' +
      '<option value="rest">REST API</option>' +
      '<option value="none">사용 안 함 (임베딩 컬럼만 / TF-IDF 폴백)</option></select>');
    embSel.value = emb.type || 'sbert';
    var embFields = Ui.el('<div></div>');
    function renderEmbFields() {
      embFields.innerHTML = '';
      if (embSel.value === 'sbert') {
        embFields.innerHTML =
          '<div class="settings-row"><label>모델명 (선택)</label><input type="text" id="emb-model" style="flex:1" value="' +
          Ui.esc(emb.model_name || '') +
          '" placeholder="비워두면 자동: 사내 로컬 경로 → snunlp/KR-SBERT-Medium-extended-patent2024-hn"></div>' +
          '<div class="disclaimer">비워두면 사내 서버에 설치된 로컬 모델 경로' +
          '(/dataiku/cache/huggingface/.../KR-SBERT-Medium-extended-patent2024-hn)를 먼저 ' +
          '시도합니다 — 네트워크 다운로드 없이 디스크에서 직접 로드되어 비용이 들지 않습니다. ' +
          '로컬 경로가 없으면 HF 캐시의 snunlp 특허 특화 모델을 순서대로 시도합니다. ' +
          '독립청구항을 임베딩하며 (GPU 자동 사용, 결과는 캐시) 사전 계산 임베딩 컬럼이 ' +
          '매핑되어 있으면 그 벡터가 우선 사용됩니다.</div>';
      } else if (embSel.value === 'llm_mesh') {
        embFields.innerHTML =
          '<div class="settings-row"><label>임베딩 LLM ID</label><input type="text" id="emb-mesh-id" style="flex:1" value="' +
          Ui.esc(emb.llm_id || '') + '" placeholder="LLM Mesh 에 등록된 임베딩 모델 ID"></div>' +
          '<div class="disclaimer">KR-SBERT 를 Local HuggingFace 연결로 Mesh 에 등록한 경우 그 ID 를 입력하세요. ID 는 서버에만 저장됩니다.</div>';
      } else if (embSel.value === 'dataset') {
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
      if (embSel.value === 'sbert') {
        conf.model_name = (document.getElementById('emb-model') || {}).value;
      } else if (embSel.value === 'llm_mesh') {
        conf.llm_id = (document.getElementById('emb-mesh-id') || {}).value;
      } else if (embSel.value === 'dataset') {
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

  /* ------------------------------------------- 작업자/팀명 (내 작업 필터) */
  /* Dataiku Webapp 은 별도 로그인 개념이 없으므로, 사용자가 입력한 작업자/팀명을
     브라우저(localStorage)에 기억해 '내 작업만 보기'의 기준으로 쓴다. */
  function getWorkerName() {
    try { return (localStorage.getItem('ipls_worker') || '').trim(); } catch (e) { return ''; }
  }
  function setWorkerName(v) {
    try { localStorage.setItem('ipls_worker', String(v || '').trim()); } catch (e) { }
  }
  function workerMatches(itemWorker, query) {
    var w = String(itemWorker || '').trim().toLowerCase();
    var q = String(query || '').trim().toLowerCase();
    if (!q) return true;
    if (!w) return false;
    return w.indexOf(q) !== -1 || q.indexOf(w) !== -1;
  }

  /* ------------------------------------------- 분석 스냅샷 (프로젝트) */
  function saveSnapshot(name, note) {
    /* 현재 분석 상태 전체 저장: Dataset + 필터 + 분석 단위/다중분류 + 보던 화면.
       작업자/팀명을 함께 기록해 목록에서 내 것만 골라볼 수 있게 한다. */
    var s = (State.config && State.config.settings) || {};
    return Api.post('/api/project/save', {
      name: name, filters: Filters.collect(), note: note || '',
      worker: getWorkerName(),
      settings: { dataset: s.dataset || null, view: State.view,
                  analysis_unit: s.analysis_unit, multiclass_mode: s.multiclass_mode }
    }).then(function () {
      Ui.toast("분석 스냅샷 '" + name + "' 이(가) 저장되었습니다.");
      refreshProjects();
    });
  }

  function loadSnapshot(name) {
    /* 저장된 분석 상태 복원: Dataset 설정 → 필터 → 저장했던 화면으로 이동.
       분석 결과는 서버 캐시에서 즉시 로드된다 (데이터가 그대로인 경우). */
    return Api.post('/api/project/load', { name: name }).then(function (d) {
      var proj = d.project || {};
      var saved = proj.settings || {};
      var patch = {};
      if (saved.dataset) patch.dataset = saved.dataset;
      if (saved.analysis_unit) patch.analysis_unit = saved.analysis_unit;
      if (saved.multiclass_mode) patch.multiclass_mode = saved.multiclass_mode;
      var pre = Object.keys(patch).length ?
        Api.post('/api/settings', patch).then(function (resp) {
          State.config.settings = resp.settings;
        }) : Promise.resolve();
      return pre.then(function () {
        State.config.filter_state = proj.filters || {};
        return Filters.load();
      }).then(function () {
        Views.render(saved.view || State.view);
        Ui.toast("분석 스냅샷 '" + name + "' 을(를) 불러왔습니다" +
          (saved.dataset ? ' (Dataset: ' + saved.dataset + ')' : '') + '.');
      });
    });
  }

  function refreshProjects() {
    Api.post('/api/project/load', {}).then(function (d) {
      State.projects = d.projects || [];
      var sel = document.getElementById('project-list');
      sel.innerHTML = '<option value="">저장된 분석…</option>';
      State.projects.forEach(function (p) {
        var o = document.createElement('option');
        o.value = p.name; o.textContent = p.name + ' (' + (p.saved_at || '') + ')';
        sel.appendChild(o);
      });
    }).catch(function () {});
  }
  document.getElementById('btn-save-project').addEventListener('click', function () {
    var name = prompt('분석 스냅샷 이름 (현재 Dataset·필터·화면 저장):');
    if (!name) return;
    saveSnapshot(name).catch(errToast);
  });
  document.getElementById('project-list').addEventListener('change', function (ev) {
    var name = ev.target.value;
    ev.target.value = '';
    if (!name) return;
    loadSnapshot(name).catch(errToast);
  });

  /* ------------------------------------------------------------- 부트 */
  document.getElementById('btn-apply-filters').addEventListener('click', Filters.apply);
  document.getElementById('btn-reset-filters').addEventListener('click', Filters.reset);
  document.querySelectorAll('#ipls-menu li[data-view]').forEach(function (li) {
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
      renderPurposeChip();
      Filters.load().then(function () {
        // 목적이 설정되어 있으면 목적 맞춤 화면을 첫 화면으로 (추천 차트 우선)
        var landing = cfg.settings.analysis_purpose ? 'purpose' : 'overview';
        Views.render(keepView ? State.view : landing);
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
  /* ------------------------------------------------- 로그인 게이트 */
  function showLogin() {
    var ov = Ui.el('<div id="ipls-login" style="position:fixed;inset:0;background:rgba(24,38,50,.55);' +
      'z-index:9999;display:flex;align-items:center;justify-content:center"></div>');
    var box = Ui.el('<div style="background:#fff;border-radius:12px;padding:28px 30px;' +
      'width:360px;box-shadow:0 12px 40px rgba(0,0,0,.25)">' +
      '<div style="font-size:17px;font-weight:800;margin-bottom:4px">🔐 IP Landscape 로그인</div>' +
      '<div style="font-size:12px;color:#647b8d;margin-bottom:14px">처음이면 자동으로 등록됩니다. ' +
      'ID는 팀명/이름, 비밀번호는 사원번호입니다.</div>' +
      '<div class="settings-row"><label style="width:80px">팀명/이름</label>' +
      '<input type="text" id="login-name" maxlength="60" placeholder="예: IP팀/홍길동" style="flex:1"></div>' +
      '<div class="settings-row"><label style="width:80px">사원번호</label>' +
      '<input type="password" id="login-pw" maxlength="30" placeholder="사원번호" style="flex:1"></div>' +
      '<button class="btn primary" id="login-btn" style="width:100%;margin-top:10px">로그인</button>' +
      '<div id="login-err" style="color:#E15759;font-size:12px;margin-top:8px"></div>' +
      '<div style="font-size:10.5px;color:#93a5b4;margin-top:10px">본 로그인은 작업 구분용 편의 ' +
      '접근 관리입니다 — 관리자 외에는 본인이 올린 데이터만 보입니다. 강한 보안이 필요한 ' +
      '접근 통제는 Dataiku 프로젝트 권한을 사용하세요.</div></div>');
    ov.appendChild(box);
    document.body.appendChild(ov);
    function doLogin() {
      var name = box.querySelector('#login-name').value.trim();
      var pw = box.querySelector('#login-pw').value.trim();
      if (!name || !pw) {
        box.querySelector('#login-err').textContent = '팀명/이름과 사원번호를 입력하세요.';
        return;
      }
      Api.post('/api/auth/login', { name: name, emp_no: pw }, '로그인 중…')
        .then(function (d) {
          Auth.save(d.token, d.user || {});
          setWorkerName(name);
          ov.remove();
          renderUserChip();
          boot(false);
        }).catch(function (e) {
          box.querySelector('#login-err').textContent = e.message;
        });
    }
    box.querySelector('#login-btn').addEventListener('click', doLogin);
    box.querySelector('#login-pw').addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') doLogin();
    });
    box.querySelector('#login-name').value = Auth.user() || getWorkerName();
  }

  function renderUserChip() {
    var bar = document.getElementById('ipls-topbar');
    if (!bar || !Auth.user()) return;
    var old = document.getElementById('ipls-userchip');
    if (old) old.remove();
    var chip = Ui.el('<span id="ipls-userchip" style="display:inline-flex;align-items:center;' +
      'gap:6px;margin-left:auto;font-size:12px;color:#46607a">👤 <b>' + Ui.esc(Auth.user()) +
      '</b>' + (Auth.isAdmin() ? ' <span class="badge good">관리자</span>' : '') +
      '<button class="btn small" id="ipls-logout">로그아웃</button></span>');
    bar.appendChild(chip);
    chip.querySelector('#ipls-logout').addEventListener('click', function () {
      Auth.clear();
      location.reload();
    });
  }

  if (Auth.token()) {
    Api.get('/api/auth/me').then(function (d) {
      if (d.user) {
        Auth.save(Auth.token(), d.user);   // is_admin 등 최신화
        renderUserChip();
        boot(false);
      } else {
        Auth.clear();
        showLogin();
      }
    }).catch(function () { renderUserChip(); boot(false); });
  } else {
    showLogin();
  }
})();

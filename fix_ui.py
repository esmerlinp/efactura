import re

with open("templates/certificacion/step_02_datos_ecf.html", "r") as f:
    text = f.read()

# We will replace from "async function generateStep2(dryRun = false) {" to the end of "function showStep2Results(data) { ... }"
# Let's find the boundaries.
start_str = "async function generateStep2(dryRun = false) {"
end_str = "if (data.rejected > 0 && data.run_number > 1) {\n            loadStep2History();\n        }\n    }"

start_idx = text.find(start_str)
end_idx = text.find(end_str) + len(end_str)

if start_idx == -1 or end_idx == -1:
    print("Could not find boundaries")
    exit(1)

new_js = """
    // --- NUEVO CODIGO CON BOTONES POR GRUPO ---
    let globalDataState = null;

    function renderGroups() {
        const section = document.getElementById("step2-results-section");
        const tables = document.getElementById("step2-result-tables");
        
        section.style.display = "block";

        let html = "";
        
        const sourceData = globalDataState ? globalDataState.results : [];
        const baseGroups = parsedStep2Data ? (parsedStep2Data._grupos_raw || {}) : {};

        [1, 2, 3, 4].forEach(gNum => {
            const g = gNum.toString();
            const gCases = baseGroups[g] || [];
            if (gCases.length === 0) return;
            
            const isManual = gNum === 4;
            
            // Check if all success for this group
            const allAccepted = gCases.every(c => {
                const r = sourceData.find(res => res.encf === c.encf && res.grupo === gNum);
                return r && r.success;
            });
            
            const btnLabel = isManual ? "Generar XML Manuales" : "Enviar a DGII";

            html += `<div class="cert-group-header"><h4>Grupo ${g} — ${isManual ? 'Subida Manual al Portal DGII' : 'Envío Automático'} (${gCases.length} casos)</h4></div>`;
            
            // Boton de envio del grupo
            html += `<div style="display: flex; gap: 10px; align-items: center; margin-bottom: 24px;">
                        <button type="button" class="cert-btn cert-btn-primary" onclick="generateStep2Group([${g}])" id="btn-group-${g}" ${allAccepted ? 'disabled' : ''}>
                            <i class="fa-solid ${allAccepted ? 'fa-check' : 'fa-play'}"></i> ${allAccepted ? 'Grupo Completado' : btnLabel}
                        </button>
                        <span id="spinner-group-${g}" style="display:none;" class="cert-progress-spinner">Cargando...</span>
                     </div>`;
                     
            if (isManual) {
                html += `<div class="cert-manual-instr" style="margin-top:-10px; margin-bottom: 20px;">
                    <i class="fa-solid fa-circle-info"></i> <strong>Instrucciones Grupo 4:</strong> 
                    Descarga cada XML y súbelo manualmente al portal DGII > Certificación > Facturas de Consumo. Marca cada uno como "Subido" cuando lo hayas hecho.
                </div>`;
            }

            html += `<table class="cert-table"><thead><tr>
                <th>Tipo</th><th>eNCF</th><th>Total</th><th>Estado</th>${gNum !== 4 ? '<th>Track ID</th>' : ''}<th>Acciones</th></tr></thead><tbody>`;
            
            gCases.forEach(c => {
                // Find result for this case
                const result = sourceData.find(res => res.encf === c.encf && res.grupo === gNum);
                
                let statusLabel = 'Pendiente';
                let statusClass = 'cert-badge-secondary';
                let errorMsg = '';
                let trackId = '—';
                
                if (result) {
                    if (result.success) {
                        statusLabel = result.dry_run ? 'Dry Run' : (result.dgii_status || 'Completado');
                        statusClass = 'cert-badge-success';
                    } else {
                        statusLabel = 'Error';
                        statusClass = 'cert-badge-danger';
                        errorMsg = result.error_message || '';
                    }
                    trackId = result.track_id || '—';
                }

                html += `<tr>
                    <td><span class="cert-badge cert-badge-info">${c.tipo}</span></td>
                    <td style="font-family:monospace; font-size:0.8rem;">${c.encf}</td>
                    <td>RD$ ${formatCurrency(c.total)}</td>
                    <td><span class="cert-badge ${statusClass}">${statusLabel}</span>${errorMsg ? '<br><small style="color:var(--accent-red);">'+errorMsg+'</small>' : ''}</td>
                    ${gNum !== 4 ? '<td style="font-family:monospace; font-size:0.75rem;">'+trackId+'</td>' : ''}
                    <td>
                        ${result && result.success ? `
                        <a href="/api/v1/certificacion/step-2/download/${c.encf}?run=${globalDataState ? globalDataState.run_number : currentStep2Run}" class="cert-btn cert-btn-secondary cert-btn-sm">
                            <i class="fa-solid fa-download"></i> XML
                        </a>` : ''}
                        ${gNum === 4 && result && result.success ? '<button class="cert-btn cert-btn-secondary cert-btn-sm" onclick="markManual(\\''+c.encf+'\\', '+(globalDataState ? globalDataState.run_number : currentStep2Run)+')" style="margin-left:4px;"><i class="fa-solid fa-check"></i> Subido</button>' : ''}
                    </td></tr>`;
            });
            html += `</tbody></table>`;
        });

        tables.innerHTML = html;
        
        // Show advance form if all groups are completed
        const allGroups = Object.keys(baseGroups);
        const allGroupsCompleted = allGroups.every(g => {
            return baseGroups[g].every(c => {
                const r = sourceData.find(res => res.encf === c.encf && res.grupo === parseInt(g));
                return r && r.success;
            });
        });
        
        const advanceForm = document.getElementById("step2-advance-form");
        if (advanceForm) {
            advanceForm.style.display = allGroupsCompleted ? "block" : "none";
        }
        
        if (globalDataState && globalDataState.rejected > 0) {
            loadStep2History();
        }
    }

    async function generateStep2Group(groups, dryRun = false) {
        if (!parsedStep2Data) { showToast("Sube el Excel primero", "warning"); return; }
        
        const g = groups[0];
        const btn = document.getElementById(`btn-group-${g}`);
        const spinner = document.getElementById(`spinner-group-${g}`);
        
        if (btn) btn.disabled = true;
        if (spinner) spinner.style.display = "inline-block";
        
        const resumeRun = !!currentStep2Run;
        
        try {
            const resp = await certFetch("/certificacion/step-2/generate", {
                method: "POST",
                body: { 
                    parsed_data: parsedStep2Data,
                    dry_run: dryRun, 
                    groups: groups, 
                    resume_run: resumeRun 
                },
            });
            const data = await resp.json();
            
            if (btn) btn.disabled = false;
            if (spinner) spinner.style.display = "none";

            if (data.success) {
                showToast(`Grupo ${g} procesado exitosamente`, "success");
            } else {
                showToast(`${data.rejected} caso(s) con error. Revisa el detalle.`, "error");
            }

            currentStep2Run = data.run_number;
            
            if (!globalDataState) {
                globalDataState = {
                    results: [],
                    run_number: data.run_number,
                    rejected: 0
                };
            }
            globalDataState.run_number = data.run_number;
            globalDataState.rejected += data.rejected;
            
            // Merge new results
            const newResults = data.results || [];
            newResults.forEach(newR => {
                const idx = globalDataState.results.findIndex(r => r.encf === newR.encf && r.grupo === newR.grupo);
                if (idx >= 0) {
                    globalDataState.results[idx] = newR;
                } else {
                    globalDataState.results.push(newR);
                }
            });

            renderGroups();
        } catch (e) {
            console.error(e);
            showToast("Error en la generación", "error");
            if (btn) btn.disabled = false;
            if (spinner) spinner.style.display = "none";
        }
    }
"""

text = text[:start_idx] + new_js + text[end_idx:]

with open("templates/certificacion/step_02_datos_ecf.html", "w") as f:
    f.write(text)

print("Replaced successfully")

(function () {
    'use strict';

    function loadBankChart() {
        const canvas = document.getElementById('bankChart');
        if (!canvas) return;

        fetch('/banks/data')
            .then(r => r.json())
            .then(data => {
                const accounts = data.accounts || [];
                const labels = accounts.map(a => a.name);
                const balances = accounts.map(a => a.currentBalance);
                const colors = accounts.map(a => {
                    if (a.type === 'banco') return '#3b82f6';
                    if (a.type === 'efectivo') return '#10b981';
                    return '#ef4444';
                });

                new Chart(canvas, {
                    type: 'bar',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Saldo (RD$)',
                            data: balances,
                            backgroundColor: colors,
                            borderRadius: 6
                        }]
                    },
                    options: {
                        responsive: true,
                        plugins: {
                            legend: { display: false }
                        },
                        scales: {
                            y: {
                                ticks: { callback: v => 'RD$ ' + v.toLocaleString() }
                            }
                        }
                    }
                });
            })
            .catch(() => {});
    }

    document.addEventListener('DOMContentLoaded', loadBankChart);
})();

/* ══════════════════════════════════════════════════════════
   AURA Canvas Renderer — Game of Life Quantum Visualization
   Smooth 30+ FPS with server polling at 5 Hz
   ══════════════════════════════════════════════════════════ */

class AuraRenderer {
    constructor(canvasId, bloomId) {
        this.canvas = document.getElementById(canvasId);
        this.bloom = document.getElementById(bloomId);
        this.ctx = this.canvas.getContext('2d');
        this.bloomCtx = this.bloom.getContext('2d');

        // Previous frame for ghost trails
        this.prevGrid = null;
        this.prevColors = null;
        this.trailAlpha = new Float32Array(256 * 256);

        // Current grid state (from server)
        this.grid = null;
        this.colors = null;
        this.density = null;  // Stochastic density map (256×256 uint8)
        this.hasDensity = false;

        // ImageData for direct pixel manipulation
        this.imageData = this.ctx.createImageData(256, 256);
        this.pixels = this.imageData.data;

        // HUD elements
        this.genEl = document.getElementById('auraGen');
        this.moodBar = document.getElementById('moodBar');
        this.cohrBar = document.getElementById('cohrBar');
        this.moodVal = document.getElementById('moodVal');
        this.cohrVal = document.getElementById('cohrVal');

        // Breathing phase
        this.breathPhase = 0;

        // Animation loop
        this._animating = false;
        this._rafId = null;
    }

    /** Called when new data arrives from server poll */
    update(data) {
        if (!data.grid_b64 || !data.quantum_colors_b64) return;

        // Store previous for ghost trails
        this.prevGrid = this.grid;
        this.prevColors = this.colors;

        // Decode new data
        this.grid = this._decodeB64(data.grid_b64);
        this.colors = this._decodeB64(data.quantum_colors_b64);

        // Decode stochastic density map if available
        if (data.density_b64) {
            this.density = this._decodeB64(data.density_b64);
            this.hasDensity = true;
        }

        // Update HUD
        this._updateHUD(data);

        // Start animation loop if not already running
        if (!this._animating) {
            this._animating = true;
            this._rafId = requestAnimationFrame(() => this._animate());
        }
    }

    /** Continuous render loop at display refresh rate */
    _animate() {
        if (!this.grid || !this.colors) {
            this._animating = false;
            return;
        }

        this._renderGrid(this.grid, this.colors);

        // Copy to bloom canvas
        this.bloomCtx.drawImage(this.canvas, 0, 0);

        this._rafId = requestAnimationFrame(() => this._animate());
    }

    _renderGrid(grid, colors) {
        const px = this.pixels;
        this.breathPhase += 0.04;
        const breathMod = 1.0 + Math.sin(this.breathPhase) * 0.06;
        const useDensity = this.hasDensity && this.density;

        for (let i = 0; i < 65536; i++) {
            const pi = i * 4;
            const ci = i * 3;

            const alive = grid[i];

            // Layer 1: Subtle ambient glow from density (halos between cells)
            if (useDensity && !alive) {
                const d = this.density[i] / 255.0;
                if (d > 0.01 && this.trailAlpha[i] < 0.05) {
                    const glow = Math.min(0.15, d * 0.5) * breathMod;
                    px[pi]     = Math.min(255, colors[ci]     * glow);
                    px[pi + 1] = Math.min(255, colors[ci + 1] * glow);
                    px[pi + 2] = Math.min(255, colors[ci + 2] * glow);
                    px[pi + 3] = 255;
                    continue;
                }
            }

            // Layer 2: Sharp cells + trails (original rendering)
            if (alive) {
                const r = Math.min(255, colors[ci] * breathMod);
                const g = Math.min(255, colors[ci + 1] * breathMod);
                const b = Math.min(255, colors[ci + 2] * breathMod);
                px[pi] = r; px[pi + 1] = g; px[pi + 2] = b; px[pi + 3] = 255;
                this.trailAlpha[i] = 1.0;
            } else {
                this.trailAlpha[i] *= 0.88;
                const alpha = this.trailAlpha[i];
                if (alpha > 0.02 && this.prevColors) {
                    px[pi]     = this.prevColors[ci]     * alpha * 0.5;
                    px[pi + 1] = this.prevColors[ci + 1] * alpha * 0.5;
                    px[pi + 2] = this.prevColors[ci + 2] * alpha * 0.5;
                    px[pi + 3] = 255;
                } else {
                    const noise = Math.random() * 3;
                    px[pi] = noise; px[pi + 1] = noise + 1; px[pi + 2] = noise;
                    px[pi + 3] = 255;
                }
            }
        }

        this.ctx.putImageData(this.imageData, 0, 0);
    }

    _updateHUD(data) {
        // Generation
        if (data.generation !== undefined) {
            this.genEl.textContent = `GEN ${data.generation.toLocaleString()}`;
        }

        // Mood
        if (data.mood !== undefined) {
            const moodPct = Math.abs(data.mood) * 100;
            this.moodBar.style.width = moodPct + '%';
            this.moodVal.textContent = data.mood.toFixed(2);
        }

        // Coherence
        if (data.coherence !== undefined) {
            const cohrPct = data.coherence * 100;
            this.cohrBar.style.width = cohrPct + '%';
            this.cohrVal.textContent = data.coherence.toFixed(2);
        }
    }

    _decodeB64(b64) {
        const binary = atob(b64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes;
    }

    destroy() {
        this._animating = false;
        if (this._rafId) {
            cancelAnimationFrame(this._rafId);
            this._rafId = null;
        }
    }
}

// Export
window.AuraRenderer = AuraRenderer;

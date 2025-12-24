/**
 * Santa Claus Animation
 * Supports multiple independent runners (Santa & Poro).
 */

(function () {
    // --- Global Shared State ---
    let chartInstance = null;
    let animationFrameId = null;
    let runners = [];

    // --- Configuration ---
    const SLED_WIDTH = 31.5;
    const PHYSICS_WIDTH = 9;
    const BASE_SPEED = 0.0010;

    /**
     * SantaRunner Class
     * Encapsulates the state and logic for a single running entity (Santa or Reindeer).
     */
    class SantaRunner {
        constructor(imagePath, startProgress = 0) {
            this.imagePath = imagePath;
            this.group = null; // ZRender Group
            this.imageShape = null; // ZRender Image

            // Dimensions (Calculated on load)
            const isMobile = window.innerWidth < 800; // Mobile breakpoint
            const baseScale = isMobile ? 0.6 : 0.8;
            this.width = SLED_WIDTH * baseScale;
            this.height = 0;
            this.pivotX = 0;
            this.pivotY = 0;

            // Physics & State
            this.direction = 1;
            this.progress = startProgress;
            this.currentSpeed = BASE_SPEED;

            // Smooth variables
            this.currentRotation = 0;
            this.scaleX = 1;
            this.currentY = null;

            // Dragging Interaction
            this.isDragging = false;
            this.dragOffsetX = 0;
            this.dragOffsetY = 0;
            this.dragVelocityX = 0;
            this.lastDragX = 0;
            this.dragHistory = [];

            // Airborne Physics
            this.isAirborne = false;
            this.momentum = { x: 0, y: 0 };

            // Lifecycle
            this.isDestroyed = false;
        }

        load(zr) {
            const img = new Image();
            img.src = this.imagePath;
            img.onload = () => {
                if (this.isDestroyed) return;
                const aspect = img.naturalWidth / img.naturalHeight;
                this.height = this.width / aspect;

                // Pivot at Center Bottom
                this.pivotX = this.width / 2;
                this.pivotY = this.height;

                // Create ZRender Elements
                const ImageShape = echarts.graphic.Image;
                const Group = echarts.graphic.Group;

                this.imageShape = new ImageShape({
                    style: {
                        image: this.imagePath,
                        x: -this.pivotX,
                        y: -this.pivotY,
                        width: this.width,
                        height: this.height
                    },
                    cursor: 'grab'
                });

                this.group = new Group();
                this.group.add(this.imageShape);

                // Add to Global ZR
                zr.add(this.group);

                this.setupInteraction(zr);

                // Force initial update to place correctly
                this.update();
            };
        }

        setupInteraction(zr) {
            const self = this;

            this.group.on('mousedown', function (e) {
                self.isDragging = true;
                self.currentSpeed = 0;

                self.dragOffsetX = e.offsetX - self.group.x;
                self.dragOffsetY = e.offsetY - self.group.y;

                self.imageShape.attr('cursor', 'grabbing');

                self.lastDragX = e.offsetX;
                self.dragVelocityX = 0;

                self.isAirborne = false;
                self.momentum = { x: 0, y: 0 };
                self.dragHistory = [];
            });

            // Note: mousemove and mouseup are usually better on global ZR
            // We listen to ZR but filter by isDragging on this instance
        }

        handleGlobalMouseMove(e) {
            if (!this.isDragging) return;

            const mx = e.offsetX;
            const my = e.offsetY;

            this.group.x = mx - this.dragOffsetX;
            this.group.y = my - this.dragOffsetY;

            // Velocity Tracking
            const dx = mx - this.lastDragX;
            this.dragVelocityX = dx;
            this.lastDragX = mx;

            const now = Date.now();
            this.dragHistory.push({ x: mx, y: my, time: now });
            while (this.dragHistory.length > 0 && now - this.dragHistory[0].time > 100) {
                this.dragHistory.shift();
            }

            this.group.dirty();
        }

        handleGlobalMouseUp(e) {
            if (!this.isDragging) return;
            this.isDragging = false;
            this.imageShape.attr('cursor', 'grab');

            // Momentum
            if (this.dragHistory.length >= 2) {
                const latest = this.dragHistory[this.dragHistory.length - 1];
                const oldest = this.dragHistory[0];
                const dt = latest.time - oldest.time;

                if (dt > 10) {
                    const vx = (latest.x - oldest.x) / dt;
                    const vy = (latest.y - oldest.y) / dt;
                    // Scale vx/vy to frame-based momentum (approx 16ms frame)
                    this.momentum.x = vx * 16;
                    this.momentum.y = vy * 16;
                }
            }

            if (Math.abs(this.momentum.x) < 2) this.momentum.x = 0;
            if (Math.abs(this.momentum.y) < 2) this.momentum.y = 0;

            this.isAirborne = true;
            this.currentY = this.group.y;
        }

        destroy(zr) {
            this.isDestroyed = true;
            if (this.group) {
                zr.remove(this.group);
                this.group = null;
            }
        }

        update() {
            if (!this.group || !chartInstance || !window.latestPredictionData) return;
            if (chartInstance.isDisposed()) return;

            // --- Dragging Wiggle ---
            if (this.isDragging) {
                const dragWiggle = Math.sin(Date.now() / 60) * 0.3;
                this.group.rotation = dragWiggle;
                this.group.dirty();
                return;
            }

            const forecast = window.latestPredictionData.forecastSeries;
            if (!forecast || forecast.length < 2) {
                this.group.hide();
                return;
            }

            // --- Rail Calculation ---
            const startPt = chartInstance.convertToPixel({ seriesId: 'forecast-line' }, forecast[0]);
            const endPt = chartInstance.convertToPixel({ seriesId: 'forecast-line' }, forecast[forecast.length - 1]);

            if (!startPt || !endPt) return;

            const startX = startPt[0];
            const endX = endPt[0];
            const totalWidth = endX - startX;

            // Direction Logic
            if (this.direction === 1 && this.progress >= 1) {
                this.direction = -1;
            } else if (this.direction === -1 && this.progress <= 0) {
                this.direction = 1;
            }

            const screenX = startX + totalWidth * this.progress;

            // Visibility Check
            const chartW = chartInstance.getWidth();
            if (screenX < -60 || screenX > chartW + 60) {
                this.group.hide();
            } else {
                this.group.show();
            }

            // --- Physics: Concave Hull Walker ---
            const halfW = PHYSICS_WIDTH / 2;
            const xL = screenX - halfW;
            const xR = screenX + halfW;
            const groundPoints = getGroundPolygon(xL, xR, forecast);

            let bestY = -99999;
            let bestAngle = 0;
            let found = false;

            for (let i = 0; i < groundPoints.length; i++) {
                for (let j = i + 1; j < groundPoints.length; j++) {
                    const p1 = groundPoints[i]; const p2 = groundPoints[j];
                    const dx = p2.x - p1.x; const dy = p2.y - p1.y;
                    if (Math.abs(dx) < 0.1) continue;

                    const m = dy / dx; const c = p1.y - m * p1.x;
                    let valid = true;
                    for (let k = 0; k < groundPoints.length; k++) {
                        if (k === i || k === j) continue;
                        const pk = groundPoints[k];
                        const lineY = m * pk.x + c;
                        if (pk.y < lineY - 0.5) { valid = false; break; }
                    }

                    if (valid) {
                        const yC = m * screenX + c;
                        if (yC > bestY) {
                            bestY = yC;
                            bestAngle = Math.atan(m);
                            found = true;
                        }
                    }
                }
            }
            if (!found) {
                if (groundPoints.length > 0) {
                    bestY = groundPoints[0].y;
                    bestAngle = 0;
                } else {
                    return;
                }
            }

            const targetY = bestY;
            const targetRotation = -bestAngle;

            // --- Airborne Logic ---
            if (this.isAirborne) {
                this.momentum.y += 0.8; // Gravity
                this.momentum.x *= 0.99;
                this.momentum.y *= 0.99;

                const nextX = this.group.x + this.momentum.x;
                const nextY = this.group.y + this.momentum.y;

                // Reset check
                const ch = chartInstance.getHeight();
                if (nextY > ch + 100) {
                    this.isAirborne = false;
                    this.group.hide();
                    this.progress = 0;
                    this.direction = 1;
                    this.currentY = null;
                    return;
                }

                // Landing Logic (Duplicate Hull Logic for nextX)
                const groundPoly = getGroundPolygon(nextX - halfW, nextX + halfW, forecast);
                let landY = -99999;
                let landFound = false;
                let landAngle = 0;

                // (Simplified landing check for brevity, logic identical to above loop)
                // We'll reuse the exact loop logic for consistency
                for (let i = 0; i < groundPoly.length; i++) {
                    for (let j = i + 1; j < groundPoly.length; j++) {
                        const p1 = groundPoly[i]; const p2 = groundPoly[j];
                        const dx = p2.x - p1.x; const dy = p2.y - p1.y;
                        if (Math.abs(dx) < 0.1) continue;
                        const m = dy / dx; const c = p1.y - m * p1.x;
                        let valid = true;
                        for (let k = 0; k < groundPoly.length; k++) {
                            if (k === i || k === j) continue;
                            if (groundPoly[k].y < (m * groundPoly[k].x + c) - 0.5) { valid = false; break; }
                        }
                        if (valid) {
                            const yC = m * nextX + c;
                            if (yC > landY) { landY = yC; landAngle = Math.atan(m); landFound = true; }
                        }
                    }
                }
                if (!landFound && groundPoly.length > 0) landY = groundPoly[0].y;

                if (landFound && nextY >= landY - 2) {
                    // Landed
                    this.isAirborne = false;
                    this.currentY = landY;
                    this.group.x = nextX;

                    // Sync Progress
                    this.progress = (nextX - startX) / totalWidth;
                    if (this.progress < 0) this.progress = 0;
                    if (this.progress > 1) this.progress = 1;

                    // Set Direction from Momentum
                    if (Math.abs(this.momentum.x) > 0.1) {
                        this.direction = this.momentum.x > 0 ? 1 : -1;
                    }
                    this.currentRotation = -landAngle;
                } else {
                    // Flying
                    this.group.x = nextX;
                    this.currentY = nextY;
                    this.group.y = nextY;
                    this.currentRotation = this.currentRotation * 0.9;
                    this.group.rotation = this.currentRotation;
                    this.group.dirty();
                    return;
                }
            }

            // --- Rail Logic (Normal Movement) ---
            const slope = Math.sin(bestAngle);
            let speedMod = Math.cos(bestAngle);
            if (speedMod < 0.01) speedMod = 0.01;
            const targetSpeed = BASE_SPEED * speedMod;

            this.currentSpeed = this.currentSpeed * 0.95 + targetSpeed * 0.05;
            this.progress += this.direction * this.currentSpeed;

            if (this.progress > 1) this.progress = 1;
            if (this.progress < 0) this.progress = 0;

            this.currentRotation = this.currentRotation * 0.7 + targetRotation * 0.3;

            // Wiggle if falling (gap > threshold)
            let extraRot = 0;
            const gravityFactor = 0.1;
            if (this.currentY !== null) {
                const vy = targetY - this.currentY;
                const slopeFactor = Math.abs(Math.sin(bestAngle));
                const flutterThreshold = 5 + 40 * slopeFactor;
                if (vy > flutterThreshold) {
                    extraRot = Math.sin(Date.now() / 80) * 0.1;
                }
            }

            // Orientation
            // If direction is -1 (Left), we flip the sprite.
            // Pukki/Poro face Right by default?
            // "Poro is always in front... pull effect"
            // If they are separate sprites, we just flip them based on their own direction.
            // Pukki.png usually faces Right?
            // let's assume images face Right.
            const targetScaleVal = this.direction;
            this.scaleX = this.scaleX * 0.85 + targetScaleVal * 0.15;

            // Bobble
            const bobble = Math.sin(Date.now() / 200 + this.progress * 100) * 1.5;
            // Added progress*100 to bobble to desync the bobble of two runners slightly

            // Update Y
            if (this.currentY === null) {
                this.currentY = targetY;
            } else {
                this.currentY = this.currentY * (1 - gravityFactor) + targetY * gravityFactor;
            }

            this.group.x = screenX;
            this.group.y = this.currentY + bobble;
            this.group.rotation = this.currentRotation + extraRot; // Add flutter
            this.group.scaleX = this.scaleX;
            this.group.dirty();
        }
    }

    // --- Helpers ---
    function getSeriesStepY(time, forecast) {
        for (let i = 0; i < forecast.length - 1; i++) {
            if (time >= forecast[i][0] && time < forecast[i + 1][0]) return forecast[i][1];
        }
        if (time < forecast[0][0]) return forecast[0][1];
        return forecast[forecast.length - 1][1];
    }

    function getGroundPolygon(xStart, xEnd, forecast) {
        const points = [];
        if (!chartInstance) return points;

        const rangeStart = chartInstance.convertFromPixel({ seriesId: 'forecast-line' }, [xStart, 0]);
        const rangeEnd = chartInstance.convertFromPixel({ seriesId: 'forecast-line' }, [xEnd, 0]);
        if (!rangeStart || !rangeEnd) return points;

        const tStart = rangeStart[0];
        const tEnd = rangeEnd[0];
        const tMin = Math.min(tStart, tEnd);
        const tMax = Math.max(tStart, tEnd);

        const yStartVal = getSeriesStepY(tStart, forecast);
        const yStartPx = chartInstance.convertToPixel({ seriesId: 'forecast-line' }, [tStart, yStartVal])[1];
        points.push({ x: xStart, y: yStartPx });

        const yEndVal = getSeriesStepY(tEnd, forecast);
        const yEndPx = chartInstance.convertToPixel({ seriesId: 'forecast-line' }, [tEnd, yEndVal])[1];
        points.push({ x: xEnd, y: yEndPx });

        for (let i = 0; i < forecast.length - 1; i++) {
            const tJump = forecast[i + 1][0];
            if (tJump > tMin && tJump < tMax) {
                const ptPx = chartInstance.convertToPixel({ seriesId: 'forecast-line' }, [tJump, 0]);
                const yPre = chartInstance.convertToPixel({ seriesId: 'forecast-line' }, [tJump, forecast[i][1]])[1];
                const yPost = chartInstance.convertToPixel({ seriesId: 'forecast-line' }, [tJump, forecast[i + 1][1]])[1];
                points.push({ x: ptPx[0], y: yPre });
                points.push({ x: ptPx[0], y: yPost });
            }
        }
        return points;
    }

    // --- Main Initialization ---
    function initSanta() {
        const container = document.getElementById('predictionChart');
        if (!container) return;

        // Clean up DOM fallback
        const oldDom = document.getElementById('jolly-santa');
        if (oldDom) oldDom.remove();

        // Get Chart
        if (typeof nfpChart !== 'undefined') {
            chartInstance = nfpChart;
        } else {
            chartInstance = echarts.getInstanceByDom(container);
        }
        if (!chartInstance) return;

        const zr = chartInstance.getZr();
        if (!zr) return;

        // Clear existing runners
        runners.forEach(r => r.destroy(zr));
        runners = [];

        // Global Mouse Listeners (Shared)
        // We need to route events to appropriate runners
        // Or just let listeners loop?
        // Easiest is to add one listener to ZR that iterates
        // But the class adds its own listeners to its Group for mousedown
        // and we need global mousemove/up.

        // Remove old global listeners if any (tricky without named functions)
        // We'll attach named functions to ZR and check a flag?
        // Actually, let's just use a singleton pattern for the global listener
        if (!zr._santaGlobalListenersAttached) {
            zr.on('mousemove', function (e) {
                runners.forEach(r => r.handleGlobalMouseMove(e));
            });
            zr.on('mouseup', function (e) {
                runners.forEach(r => r.handleGlobalMouseUp(e));
            });
            zr.on('globalout', function (e) {
                runners.forEach(r => r.handleGlobalMouseUp(e));
            });
            zr._santaGlobalListenersAttached = true;
        }

        // Create Runners
        // 1. Pukki
        const pukki = new SantaRunner('pukki.png', 0.0);
        pukki.load(zr);

        // 2. Poro (Reindeer) - Starts slightly ahead
        const poro = new SantaRunner('poro.png', 0.03);
        poro.load(zr);

        runners.push(pukki);
        runners.push(poro);

        startAnimation();
    }

    function startAnimation() {
        if (animationFrameId) cancelAnimationFrame(animationFrameId);
        let lastTime = 0;
        const fpsInterval = 1000 / 30;

        function animate(timestamp) {
            if (!lastTime) lastTime = timestamp;
            const elapsed = timestamp - lastTime;
            if (elapsed > fpsInterval) {
                lastTime = timestamp - (elapsed % fpsInterval);
                runners.forEach(r => r.update());
            }
            animationFrameId = requestAnimationFrame(animate);
        }
        animationFrameId = requestAnimationFrame(animate);
    }

    // --- Bootstrapping ---
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initSanta);
    } else {
        initSanta();
    }
    window.addEventListener('prediction-data-ready', () => { setTimeout(initSanta, 100); });
    window.addEventListener('resize', () => { if (chartInstance) chartInstance.resize(); });
    // Note: initSanta is NOT automatically called on resize by this logic only chart resize.
    // That's fine, the update loop handles positioning.

})();

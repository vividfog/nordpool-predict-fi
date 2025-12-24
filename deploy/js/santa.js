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
        constructor(imagePath, role, startProgress = 0, leashOpts = { x: 0, y: 0 }) {
            this.role = role; // 'santa' or 'reindeer'
            this.imagePath = imagePath;
            this.group = null; // ZRender Group
            this.imageShape = null; // ZRender Image
            this.leashOpts = leashOpts;

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
            this.isThrown = false; // True if flight was initiated by drag

            // Interaction Helpers
            this.lastBobble = 0;
            this.justSnapped = false; // Prevents progress overwrite after formation snap
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

            // Immediately update direction while dragging to reflect visual intent
            if (Math.abs(dx) > 0) {
                this.direction = Math.sign(dx);
            }

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

            if (Math.abs(this.momentum.x) > 1) {
                this.direction = Math.sign(this.momentum.x);
            }

            this.isAirborne = true;
            this.isThrown = true;

            // Clear isThrown on others to establish leadership
            runners.forEach(r => { if (r !== this) r.isThrown = false; });

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

            // --- Passive Follower Logic ---
            // If another runner is the "Thrower" (dragged or thrown), and I am not, I am passive.
            let thrower = null;
            if (runners.length > 1) {
                thrower = runners.find(r => r.isThrown || r.isDragging);
            }

            // If I am not the thrower, but there IS a thrower, I am a passive follower.
            const isPassive = (thrower && thrower !== this);

            if (isPassive) {
                // Passive follower: do NOT copy thrower's direction during drag.
                // Direction will sync on landing via formation snap.
                // Just skip Rail Logic (walking) — handled by leash constraint.
            }

            // --- Rail Calculation ---
            const startPt = chartInstance.convertToPixel({ seriesId: 'forecast-line' }, forecast[0]);
            const endPt = chartInstance.convertToPixel({ seriesId: 'forecast-line' }, forecast[forecast.length - 1]);

            if (!startPt || !endPt) return;

            const startX = startPt[0];
            const endX = endPt[0];
            const totalWidth = endX - startX;
            this.lastTotalWidth = totalWidth; // Store for physics helpers

            // Direction Logic
            // Reindeer (Poro) is the Leader. He decides when to turn at edges.
            // Santa (Pukki) follows Reindeer unless he is being dragged/thrown himself.
            if (this.role === 'reindeer') {
                if (this.direction === 1 && this.progress >= 1) {
                    this.direction = -1;
                } else if (this.direction === -1 && this.progress <= 0) {
                    this.direction = 1;
                }
            } else {
                // I am Santa
                if (!this.isDragging && !this.isThrown) {
                    // If just walking, copy Reindeer
                    const poro = runners.find(r => r.role === 'reindeer');
                    if (poro) {
                        this.direction = poro.direction;
                    }
                } else {
                    // If I am being interacted with, I can turn at edges to stay in bounds
                    if (this.direction === 1 && this.progress >= 1) {
                        this.direction = -1;
                    } else if (this.direction === -1 && this.progress <= 0) {
                        this.direction = 1;
                    }
                }
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

                let nextX = this.group.x + this.momentum.x;
                let nextY = this.group.y + this.momentum.y;

                // --- Edge Bounce (Bouncy Boundaries) ---
                const chartW = chartInstance.getWidth();
                const edgeMargin = 20; // Bounce before going fully off-screen
                const bounceFactor = 0.6; // Energy loss on bounce

                // Left edge bounce
                if (nextX < startX - edgeMargin) {
                    nextX = startX - edgeMargin;
                    this.momentum.x = -this.momentum.x * bounceFactor;
                    this.direction = 1; // Now moving right
                }
                // Right edge bounce
                if (nextX > endX + edgeMargin) {
                    nextX = endX + edgeMargin;
                    this.momentum.x = -this.momentum.x * bounceFactor;
                    this.direction = -1; // Now moving left
                }

                // Bottom edge - bounce back up (instead of falling off)
                const ch = chartInstance.getHeight();
                if (nextY > ch - 10) {
                    nextY = ch - 10;
                    this.momentum.y = -this.momentum.y * bounceFactor;
                }

                // Landing Logic (Hull check for ground)
                const groundPoly = getGroundPolygon(nextX - halfW, nextX + halfW, forecast);
                let landY = -99999;
                let landFound = false;
                let landAngle = 0;

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
                    this.momentum = { x: 0, y: 0 };

                    // --- Formation Snap (Leader Always Wins) ---
                    // Always snap formation on landing, regardless of who was thrown
                    const pukki = runners.find(r => r.role === 'santa');
                    const poro = runners.find(r => r.role === 'reindeer');

                    if (pukki && poro) {
                        const OFFSET = 0.02;
                        let landingProgress = (nextX - startX) / totalWidth;

                        // Direction: use this runner's direction (from momentum/bounce)
                        const landingDir = this.direction;
                        pukki.direction = landingDir;
                        poro.direction = landingDir;

                        // Stop momentum for both
                        pukki.momentum = { x: 0, y: 0 };
                        poro.momentum = { x: 0, y: 0 };

                        // Poro is always the leader - establish Poro's position first
                        if (this.role === 'reindeer') {
                            // Poro landed - use landing position
                            poro.progress = landingProgress;
                        } else {
                            // Pukki landed - Poro goes in front
                            poro.progress = landingProgress + (landingDir * OFFSET);
                        }

                        // Clamp Poro
                        poro.progress = Math.max(0, Math.min(1, poro.progress));

                        // Pukki is always behind Poro
                        pukki.progress = poro.progress - (landingDir * OFFSET);
                        pukki.progress = Math.max(0, Math.min(1, pukki.progress));

                        // Apply positions
                        pukki.group.x = startX + totalWidth * pukki.progress;
                        poro.group.x = startX + totalWidth * poro.progress;

                        // Ground-snap both and clear states
                        [pukki, poro].forEach(r => {
                            const groundY = findGroundY(r.group.x, forecast, chartInstance);
                            if (groundY !== null) {
                                r.currentY = groundY;
                                r.group.y = groundY;
                            }
                            r.isAirborne = false;
                            r.isThrown = false;
                            // Note: Do NOT clear isDragging here — that's mouse-controlled
                            r.justSnapped = true; // Prevent progress overwrite this frame
                            if (r.imageShape && !r.isDragging) r.imageShape.attr('cursor', 'grab');
                        });
                    }

                    this.currentRotation = -landAngle;
                } else {
                    // Still flying
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
            if (!isPassive && !this.justSnapped) {
                const slope = Math.sin(bestAngle);
                let speedMod = Math.cos(bestAngle);
                if (speedMod < 0.01) speedMod = 0.01;
                const targetSpeed = BASE_SPEED * speedMod;

                this.currentSpeed = this.currentSpeed * 0.95 + targetSpeed * 0.05;
                this.progress += this.direction * this.currentSpeed;

                if (this.progress > 1) this.progress = 1;
                if (this.progress < 0) this.progress = 0;

                this.currentRotation = this.currentRotation * 0.7 + targetRotation * 0.3;
            } else {
                // Passive: Just damp rotation towards 0 or similar if grounded? 
                // Actually, if passive and ground-sliding (dragged), we might want to align to ground?
                // For now, let's say if grounded & passive, we DO align to ground but DON'T move progress autonomously.
                if (this.currentY !== null) {
                    this.currentRotation = this.currentRotation * 0.7 + targetRotation * 0.3;
                }
            }

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
            const targetScaleVal = this.direction;
            this.scaleX = this.scaleX * 0.85 + targetScaleVal * 0.15;

            // Snap to full flip when close enough (prevents half-flipped states)
            if (Math.abs(this.scaleX) > 0.95) {
                this.scaleX = Math.sign(this.scaleX);
            }

            // Bobble
            const bobble = Math.sin(Date.now() / 200 + this.progress * 100) * 1.5;
            this.lastBobble = bobble;

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

            // Clear justSnapped at end of frame
            this.justSnapped = false;
        }
    }

    /**
     * Leash Class
     * visually connects two runners and handles constraints.
     */
    class Leash {
        constructor() {
            this.line = null;
            this.maxDistance = 60; // Max pixels between attachment points
        }

        init(zr) {
            const Polyline = echarts.graphic.Polyline;
            this.line = new Polyline({
                shape: { points: [] },
                style: {
                    stroke: 'red',
                    lineWidth: 2,
                    lineDash: [0, 0] // Solid red line
                },
                z: 0 // Behind runners
            });
            zr.add(this.line);
        }

        update(runner1, runner2, chart) {
            if (!this.line || !runner1.group || !runner2.group) return;

            // 1. Get Attachment Points
            // Runner 1 is usually Santa (left/back), Runner 2 is Poro (right/front)
            // But we can check positions.
            const p1 = this.getAttachPoint(runner1);
            const p2 = this.getAttachPoint(runner2);

            // 2. Resolve Constraints (Physics)
            // If dragging, pull the other.
            this.resolveConstraint(runner1, runner2, p1, p2, chart);

            // 3. Draw Leash (with gravity sag)
            // Recalculate points after constraint possibly moved them
            const p1_new = this.getAttachPoint(runner1);
            const p2_new = this.getAttachPoint(runner2);

            // Simple catenary-like curve
            const midX = (p1_new.x + p2_new.x) / 2;
            const midY = (p1_new.y + p2_new.y) / 2 + 10; // Dip by 10px

            this.line.setShape({
                points: [[p1_new.x, p1_new.y], [midX, midY], [p2_new.x, p2_new.y]]
            });

            // --- Formation Enforcement (Per-Frame Soft Nudge) ---
            // When grounded and not interacting, ensure Pukki stays behind Poro
            const pukki = runners.find(r => r.role === 'santa');
            const poro = runners.find(r => r.role === 'reindeer');

            if (pukki && poro &&
                !pukki.isDragging && !poro.isDragging &&
                !pukki.isAirborne && !poro.isAirborne) {

                const OFFSET = 0.02;
                const targetPukkiProgress = poro.progress - (poro.direction * OFFSET);
                const clampedTarget = Math.max(0, Math.min(1, targetPukkiProgress));

                // Soft nudge (10% per frame) to avoid jarring snaps during normal walking
                const nudgeFactor = 0.1;
                pukki.progress = pukki.progress * (1 - nudgeFactor) + clampedTarget * nudgeFactor;
            }
        }

        getAttachPoint(runner) {
            // pivotX is width/2, pivotY is height. 
            // group.x, group.y is the pivot point (bottom center).
            const offsetX = (runner.leashOpts?.x || 0) * runner.width * runner.direction;
            const offsetY = (runner.leashOpts?.y || 0) * runner.height;

            return {
                x: runner.group.x + offsetX,
                y: runner.group.y - (runner.height / 2) + offsetY
            };
        }

        resolveConstraint(r1, r2, p1, p2, chart) {
            // "Leash" logic:
            // 1. If dragging one, the other is pulled if distance > max.
            // 2. If neither is dragging (both airborne/thrown), they pull each other.

            const dx = p2.x - p1.x;
            const dy = p2.y - p1.y;
            const dist = Math.sqrt(dx * dx + dy * dy);

            // Allow some slack, but if exceeding max, pull.
            if (dist <= this.maxDistance) return;

            // Calculate Correction
            // How much to move to satisfy distance = maxDistance
            const correction = (dist - this.maxDistance) / dist;
            const cx = dx * correction;
            const cy = dy * correction;

            // Determine weights (0 = anchor, 0.5 = shared, 1 = pulled)
            // By default, share the correction (free flight)
            let w1 = 0.5;
            let w2 = 0.5;

            // If one is dragging, it becomes the rigid anchor (weight 0)
            if (r1.isDragging && !r2.isDragging) {
                w1 = 0; w2 = 1;
            } else if (r2.isDragging && !r1.isDragging) {
                w1 = 1; w2 = 0;
            } else if (r1.isDragging && r2.isDragging) {
                return; // Both fixed by mouse, can't resolve constraint
            }

            // Apply corrections
            // If we need to bring them closer:
            // r1 should move towards r2 (positive cx, cy)
            // r2 should move towards r1 (negative cx, cy)

            if (w1 > 0) {
                const mx = cx * w1;
                const my = cy * w1;
                r1.group.x += mx;
                r1.group.y += my;

                // If pulled UP specifically (my < -2), or already airborne, stay airborne.
                // Otherwise (sliding on ground), stay grounded.
                if (r1.isAirborne || my < -2) {
                    r1.isAirborne = true;
                }

                // Remove bobble from visual Y to get physics Y
                r1.currentY = r1.group.y - (r1.lastBobble || 0);

                // Sync Progress (approximate based on shift)
                if (r1.lastTotalWidth) {
                    r1.progress += mx / r1.lastTotalWidth;
                    if (r1.progress < 0) r1.progress = 0;
                    if (r1.progress > 1) r1.progress = 1;
                }
            }

            if (w2 > 0) {
                const mx = -cx * w2;
                const my = -cy * w2;
                r2.group.x += mx;
                r2.group.y += my;

                if (r2.isAirborne || my < -2) {
                    r2.isAirborne = true;
                }

                r2.currentY = r2.group.y - (r2.lastBobble || 0);

                if (r2.lastTotalWidth) {
                    r2.progress += mx / r2.lastTotalWidth;
                    if (r2.progress < 0) r2.progress = 0;
                    if (r2.progress > 1) r2.progress = 1;
                }
            }
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

    function findGroundY(x, forecast, chart) {
        // Quick lookup of ground Y at exactly X
        // We use the same hull logic but simplified for a single vertical line
        // A simple range around X
        const poly = getGroundPolygon(x - 5, x + 5, forecast);

        let bestY = -99999;
        let found = false;

        // Concave hull walker for the small segment
        for (let i = 0; i < poly.length; i++) {
            for (let j = i + 1; j < poly.length; j++) {
                const p1 = poly[i]; const p2 = poly[j];
                const dx = p2.x - p1.x; const dy = p2.y - p1.y;
                if (Math.abs(dx) < 0.1) continue;

                const m = dy / dx; const c = p1.y - m * p1.x;
                let valid = true;
                for (let k = 0; k < poly.length; k++) {
                    if (k === i || k === j) continue;
                    // Check if any point is strictly ABOVE the line (since Y is pixel coords, 'above' means smaller Y? 
                    // No, standard coord system here: higher Y is DOWN usually in canvas, but eCharts?
                    // "pk.y < lineY - 0.5" in main loop. 
                    // This implies Y increases downwards? Or upwards?
                    // Ground usually implies we want the "Highest" visual point (Lowest Y in canvas?).
                    // But code uses `yC > bestY`.
                    // If `yC > bestY`, we are maximizing Y.
                    // If Y increases Down, maximizing Y means finding the lowest point?
                    // Wait, chart ground is usually at bottom.
                    // If Y axis is standard screen coords (0 at top), high Y is bottom.
                    // "pk.y < lineY" -> point is above line.
                    // If we want a "Concave Hull" representing the surface we walk on (the 'top' of the area chart),
                    // we usually want the minimal Y envelop (highest on screen).
                    // But the loop does `yC > bestY`.
                    // Let's stick to strict copy of the logic in `update` to be safe.
                    // Logic in update:
                    // if (pk.y < lineY - 0.5) { valid = false; }
                    // if (valid && yC > bestY) { bestY = yC }

                    if (poly[k].y < (m * poly[k].x + c) - 0.5) { valid = false; break; }
                }

                if (valid) {
                    const yC = m * x + c;
                    if (yC > bestY) {
                        bestY = yC;
                        found = true;
                    }
                }
            }
        }
        if (found) return bestY;
        if (poly.length > 0) return poly[0].y;
        return null;
    }

    // --- Main Initialization ---
    let leash = null;

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

        if (leash && leash.line) {
            zr.remove(leash.line);
        }

        // Global Mouse Listeners (Shared)
        // ... (Keep existing listener logic)
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
        const pukki = new SantaRunner('pukki.png', 'santa', 0.0);
        pukki.load(zr);

        // 2. Poro (Reindeer) - Starts slightly ahead
        const poro = new SantaRunner('poro.png', 'reindeer', 0.02);
        poro.load(zr);

        runners.push(pukki);
        runners.push(poro);

        // Init Leash
        leash = new Leash();
        leash.init(zr);

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

                // Update Leash
                if (leash && runners.length >= 2) {
                    leash.update(runners[0], runners[1], chartInstance);
                }
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

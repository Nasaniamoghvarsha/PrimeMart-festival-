document.addEventListener('DOMContentLoaded', function() {
    // Configuration
    const config = {
        count: 50,          // Number of snowflakes
        minSize: 1,         // Minimum size of snowflakes in pixels
        maxSize: 5,         // Maximum size of snowflakes in pixels
        speed: 1,           // Base falling speed
        wind: 0.2,          // Wind effect (0 = no wind, positive = right, negative = left)
        color: '#ffffff',   // Snowflake color
        opacity: 0.8,       // Snowflake opacity
        zIndex: 9999        // Ensure snowflakes appear above other elements
    };

    // Create snowflakes
    for (let i = 0; i < config.count; i++) {
        createSnowflake();
    }

    function createSnowflake() {
        const snowflake = document.createElement('div');
        snowflake.className = 'snowflake';
        
        // Random size
        const size = Math.random() * (config.maxSize - config.minSize) + config.minSize;
        
        // Random starting position
        const startX = Math.random() * window.innerWidth;
        const startY = -10;
        
        // Random animation duration (falling speed)
        const duration = Math.random() * 10 + 10;
        
        // Random delay for staggered appearance
        const delay = Math.random() * -20;
        
        // Apply styles
        snowflake.style.cssText = `
            position: fixed;
            width: ${size}px;
            height: ${size}px;
            background: ${config.color};
            border-radius: 50%;
            pointer-events: none;
            opacity: ${config.opacity};
            left: ${startX}px;
            top: ${startY}px;
            z-index: ${config.zIndex};
            will-change: transform, opacity;
            animation: fall ${duration}s linear ${delay}s infinite;
        `;

        // Add the snowflake to the body
        document.body.appendChild(snowflake);

        // Remove snowflake after animation completes to prevent memory issues
        setTimeout(() => {
            if (snowflake.parentNode) {
                snowflake.remove();
                createSnowflake(); // Create a new snowflake to replace this one
            }
        }, (duration + 20) * 1000);
    }

    // Add keyframes for falling animation
    const style = document.createElement('style');
    style.textContent = `
        @keyframes fall {
            0% {
                transform: translate(0, 0) rotate(0deg);
                opacity: 0;
            }
            10% {
                opacity: ${config.opacity};
            }
            90% {
                opacity: ${config.opacity};
            }
            100% {
                transform: translate(${config.wind * 100}px, 100vh) rotate(360deg);
                opacity: 0;
            }
        }
    `;
    document.head.appendChild(style);

    // Handle window resize
    window.addEventListener('resize', function() {
        // This ensures snowflakes stay within view on resize
        // The snowflakes will naturally adjust their positions on the next animation frame
    });
});

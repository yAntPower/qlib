package main

import (
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"
)

// BinanceTradingSignal represents a trading signal from qlib analyzer for Binance symbols
type BinanceTradingSignal struct {
	Symbol                string                 `json:"symbol"`
	Timestamp            string                 `json:"timestamp"`
	Price                float64                `json:"price"`
	Volume               float64                `json:"volume"`
	Recommendation       string                 `json:"recommendation"`       // BUY, SELL, HOLD
	Confidence           float64                `json:"confidence"`           // 0.0 - 1.0
	TechnicalIndicators  map[string]interface{} `json:"technical_indicators"`
	MLPrediction         map[string]interface{} `json:"ml_prediction"`
}

// SignalResponse represents the API response from qlib analyzer
type SignalResponse struct {
	Status    string                           `json:"status"`
	Timestamp string                           `json:"timestamp"`
	Data      map[string]BinanceTradingSignal  `json:"data"`
}

// TradingConfig holds trading configuration
type TradingConfig struct {
	MinConfidence     float64   `json:"min_confidence"`      // Minimum confidence to execute trades
	MaxPositions      int       `json:"max_positions"`       // Maximum concurrent positions
	StopLossPercent   float64   `json:"stop_loss_percent"`   // Stop loss percentage
	TakeProfitPercent float64   `json:"take_profit_percent"` // Take profit percentage
	WatchSymbols      []string  `json:"watch_symbols"`       // Symbols to monitor
	TradingEnabled    bool      `json:"trading_enabled"`     // Enable/disable actual trading
}

// Position represents an open trading position
type Position struct {
	Symbol         string    `json:"symbol"`
	Side           string    `json:"side"`           // BUY or SELL
	Size           float64   `json:"size"`           // Position size
	EntryPrice     float64   `json:"entry_price"`    // Entry price
	CurrentPrice   float64   `json:"current_price"`  // Current price
	PnL            float64   `json:"pnl"`            // Profit/Loss
	Timestamp      time.Time `json:"timestamp"`      // Position open time
	StopLoss       float64   `json:"stop_loss"`      // Stop loss price
	TakeProfit     float64   `json:"take_profit"`    // Take profit price
}

// BinanceQlibClient handles communication with qlib analyzer
type BinanceQlibClient struct {
	BaseURL         string
	Client          *http.Client
	Config          TradingConfig
	OpenPositions   map[string]*Position
	TradingHistory  []Position
}

// NewBinanceQlibClient creates a new client with default configuration
func NewBinanceQlibClient(baseURL string) *BinanceQlibClient {
	return &BinanceQlibClient{
		BaseURL: baseURL,
		Client:  &http.Client{Timeout: 10 * time.Second},
		Config: TradingConfig{
			MinConfidence:     0.7,
			MaxPositions:      5,
			StopLossPercent:   0.02,   // 2%
			TakeProfitPercent: 0.05,   // 5%
			WatchSymbols: []string{
				"BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "DOTUSDT",
				"XRPUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT", "MATICUSDT",
			},
			TradingEnabled: false, // Set to true when ready for live trading
		},
		OpenPositions:  make(map[string]*Position),
		TradingHistory: make([]Position, 0),
	}
}

// LoadConfig loads trading configuration from file
func (c *BinanceQlibClient) LoadConfig(configPath string) error {
	data, err := ioutil.ReadFile(configPath)
	if err != nil {
		return err
	}
	
	return json.Unmarshal(data, &c.Config)
}

// SaveConfig saves trading configuration to file
func (c *BinanceQlibClient) SaveConfig(configPath string) error {
	data, err := json.MarshalIndent(c.Config, "", "  ")
	if err != nil {
		return err
	}
	
	return ioutil.WriteFile(configPath, data, 0644)
}

// GetLatestSignals fetches the latest trading signals for all monitored symbols
func (c *BinanceQlibClient) GetLatestSignals() (map[string]BinanceTradingSignal, error) {
	resp, err := c.Client.Get(c.BaseURL + "/signals/latest")
	if err != nil {
		return nil, fmt.Errorf("failed to fetch signals: %v", err)
	}
	defer resp.Body.Close()

	body, err := ioutil.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %v", err)
	}

	var signalResp SignalResponse
	if err := json.Unmarshal(body, &signalResp); err != nil {
		return nil, fmt.Errorf("failed to parse response: %v", err)
	}

	if signalResp.Status != "success" {
		return nil, fmt.Errorf("API error: %s", signalResp.Status)
	}

	return signalResp.Data, nil
}

// GetSignalsForSymbols fetches signals for specific symbols
func (c *BinanceQlibClient) GetSignalsForSymbols(symbols []string) (map[string]BinanceTradingSignal, error) {
	url := c.BaseURL + "/signals?symbols=" + strings.Join(symbols, ",")

	resp, err := c.Client.Get(url)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch signals: %v", err)
	}
	defer resp.Body.Close()

	body, err := ioutil.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %v", err)
	}

	var signalResp SignalResponse
	if err := json.Unmarshal(body, &signalResp); err != nil {
		return nil, fmt.Errorf("failed to parse response: %v", err)
	}

	return signalResp.Data, nil
}

// AnalyzeSignal performs technical analysis on the signal
func (c *BinanceQlibClient) AnalyzeSignal(signal BinanceTradingSignal) (bool, string) {
	// Extract technical indicators
	tech := signal.TechnicalIndicators
	
	reasons := make([]string, 0)
	score := 0
	
	// RSI Analysis
	if rsi, ok := tech["rsi"].(float64); ok {
		if signal.Recommendation == "BUY" && rsi < 30 {
			score += 2
			reasons = append(reasons, fmt.Sprintf("RSI oversold (%.1f)", rsi))
		} else if signal.Recommendation == "SELL" && rsi > 70 {
			score += 2
			reasons = append(reasons, fmt.Sprintf("RSI overbought (%.1f)", rsi))
		}
	}
	
	// Moving Average Analysis
	if priceVsMa5, ok := tech["price_vs_ma5"].(float64); ok {
		if signal.Recommendation == "BUY" && priceVsMa5 > 2 {
			score += 1
			reasons = append(reasons, fmt.Sprintf("Price above MA5 (+%.1f%%)", priceVsMa5))
		} else if signal.Recommendation == "SELL" && priceVsMa5 < -2 {
			score += 1
			reasons = append(reasons, fmt.Sprintf("Price below MA5 (%.1f%%)", priceVsMa5))
		}
	}
	
	// MACD Analysis
	if macdLine, ok := tech["macd_line"].(float64); ok {
		if macdSignal, ok := tech["macd_signal"].(float64); ok {
			if signal.Recommendation == "BUY" && macdLine > macdSignal {
				score += 1
				reasons = append(reasons, "MACD bullish crossover")
			} else if signal.Recommendation == "SELL" && macdLine < macdSignal {
				score += 1
				reasons = append(reasons, "MACD bearish crossover")
			}
		}
	}
	
	// Confidence threshold
	confidenceScore := 0
	if signal.Confidence >= c.Config.MinConfidence {
		confidenceScore = 2
		reasons = append(reasons, fmt.Sprintf("High confidence (%.1f%%)", signal.Confidence*100))
	}
	
	totalScore := score + confidenceScore
	shouldTrade := totalScore >= 3 && signal.Confidence >= c.Config.MinConfidence
	
	reasonText := strings.Join(reasons, ", ")
	if reasonText == "" {
		reasonText = "No clear signal"
	}
	
	return shouldTrade, reasonText
}

// ExecuteBuyOrder simulates or executes a buy order
func (c *BinanceQlibClient) ExecuteBuyOrder(symbol string, signal BinanceTradingSignal) error {
	// Check if we already have a position in this symbol
	if _, exists := c.OpenPositions[symbol]; exists {
		return fmt.Errorf("already have position in %s", symbol)
	}
	
	// Check max positions limit
	if len(c.OpenPositions) >= c.Config.MaxPositions {
		return fmt.Errorf("maximum positions (%d) reached", c.Config.MaxPositions)
	}
	
	// Calculate position size (this is a simplified example)
	positionSize := 100.0 // Example: $100 per position
	
	// Calculate stop loss and take profit
	stopLoss := signal.Price * (1 - c.Config.StopLossPercent)
	takeProfit := signal.Price * (1 + c.Config.TakeProfitPercent)
	
	position := &Position{
		Symbol:       symbol,
		Side:         "BUY",
		Size:         positionSize / signal.Price, // Convert to quantity
		EntryPrice:   signal.Price,
		CurrentPrice: signal.Price,
		PnL:          0,
		Timestamp:    time.Now(),
		StopLoss:     stopLoss,
		TakeProfit:   takeProfit,
	}
	
	if c.Config.TradingEnabled {
		// Here you would integrate with Binance API to place actual order
		log.Printf("🔥 LIVE BUY ORDER: %s at $%.4f (Size: %.6f)", symbol, signal.Price, position.Size)
		
		// Example Binance API call (you need to implement this):
		// err := c.PlaceBinanceOrder(symbol, "BUY", position.Size, signal.Price)
		// if err != nil {
		//     return fmt.Errorf("failed to place buy order: %v", err)
		// }
	} else {
		log.Printf("📈 SIMULATED BUY: %s at $%.4f (Size: %.6f, SL: $%.4f, TP: $%.4f)", 
			symbol, signal.Price, position.Size, stopLoss, takeProfit)
	}
	
	c.OpenPositions[symbol] = position
	return nil
}

// ExecuteSellOrder simulates or executes a sell order
func (c *BinanceQlibClient) ExecuteSellOrder(symbol string, signal BinanceTradingSignal) error {
	position, exists := c.OpenPositions[symbol]
	if !exists || position.Side != "BUY" {
		return fmt.Errorf("no buy position to sell for %s", symbol)
	}
	
	// Calculate P&L
	pnl := (signal.Price - position.EntryPrice) * position.Size
	pnlPercent := (signal.Price - position.EntryPrice) / position.EntryPrice * 100
	
	if c.Config.TradingEnabled {
		// Here you would integrate with Binance API to place actual order
		log.Printf("🔥 LIVE SELL ORDER: %s at $%.4f (P&L: $%.2f, %.2f%%)", 
			symbol, signal.Price, pnl, pnlPercent)
		
		// Example Binance API call:
		// err := c.PlaceBinanceOrder(symbol, "SELL", position.Size, signal.Price)
		// if err != nil {
		//     return fmt.Errorf("failed to place sell order: %v", err)
		// }
	} else {
		log.Printf("📉 SIMULATED SELL: %s at $%.4f (P&L: $%.2f, %.2f%%)", 
			symbol, signal.Price, pnl, pnlPercent)
	}
	
	// Close position
	position.CurrentPrice = signal.Price
	position.PnL = pnl
	c.TradingHistory = append(c.TradingHistory, *position)
	delete(c.OpenPositions, symbol)
	
	return nil
}

// UpdatePositions updates current prices and P&L for open positions
func (c *BinanceQlibClient) UpdatePositions(signals map[string]BinanceTradingSignal) {
	for symbol, position := range c.OpenPositions {
		if signal, exists := signals[symbol]; exists {
			position.CurrentPrice = signal.Price
			if position.Side == "BUY" {
				position.PnL = (signal.Price - position.EntryPrice) * position.Size
			}
			
			// Check stop loss and take profit
			if position.Side == "BUY" {
				if signal.Price <= position.StopLoss {
					log.Printf("🛑 STOP LOSS TRIGGERED: %s at $%.4f", symbol, signal.Price)
					c.ExecuteSellOrder(symbol, signal)
				} else if signal.Price >= position.TakeProfit {
					log.Printf("🎯 TAKE PROFIT TRIGGERED: %s at $%.4f", symbol, signal.Price)
					c.ExecuteSellOrder(symbol, signal)
				}
			}
		}
	}
}

// PrintPositions displays current positions
func (c *BinanceQlibClient) PrintPositions() {
	fmt.Println("\n📊 Current Positions:")
	fmt.Println("Symbol    | Side | Entry    | Current  | P&L      | P&L%")
	fmt.Println("----------|------|----------|----------|----------|----------")
	
	totalPnL := 0.0
	for symbol, pos := range c.OpenPositions {
		pnlPercent := pos.PnL / (pos.EntryPrice * pos.Size) * 100
		totalPnL += pos.PnL
		
		fmt.Printf("%-9s | %-4s | $%-7.4f | $%-7.4f | $%-7.2f | %+6.2f%%\n",
			symbol, pos.Side, pos.EntryPrice, pos.CurrentPrice, pos.PnL, pnlPercent)
	}
	
	if len(c.OpenPositions) > 0 {
		fmt.Printf("----------|------|----------|----------|----------|----------\n")
		fmt.Printf("Total P&L: $%.2f\n", totalPnL)
	} else {
		fmt.Println("No open positions")
	}
}

// ProcessTradingSignals processes signals and makes trading decisions
func (c *BinanceQlibClient) ProcessTradingSignals(signals map[string]BinanceTradingSignal) {
	fmt.Printf("\n⏰ Processing %d signals at %s\n", len(signals), time.Now().Format("15:04:05"))
	
	// Update existing positions first
	c.UpdatePositions(signals)
	
	// Process signals for watched symbols
	for _, watchSymbol := range c.Config.WatchSymbols {
		if signal, exists := signals[watchSymbol]; exists {
			shouldTrade, reason := c.AnalyzeSignal(signal)
			
			fmt.Printf("📊 %s: %s (Conf: %.1f%%) - %s", 
				watchSymbol, signal.Recommendation, signal.Confidence*100, reason)
			
			if shouldTrade {
				switch signal.Recommendation {
				case "BUY":
					if err := c.ExecuteBuyOrder(watchSymbol, signal); err != nil {
						fmt.Printf(" ❌ Buy failed: %s", err.Error())
					} else {
						fmt.Printf(" ✅ Buy executed")
					}
				case "SELL":
					if err := c.ExecuteSellOrder(watchSymbol, signal); err != nil {
						fmt.Printf(" ❌ Sell failed: %s", err.Error())
					} else {
						fmt.Printf(" ✅ Sell executed")
					}
				case "HOLD":
					fmt.Printf(" ⏸️ Holding")
				}
			} else {
				fmt.Printf(" ⏭️ No action")
			}
			fmt.Println()
		}
	}
	
	// Print current positions
	c.PrintPositions()
}

// SaveTradingHistory saves trading history to file
func (c *BinanceQlibClient) SaveTradingHistory(filename string) error {
	data, err := json.MarshalIndent(c.TradingHistory, "", "  ")
	if err != nil {
		return err
	}
	
	return ioutil.WriteFile(filename, data, 0644)
}

// GetTradingStats calculates trading statistics
func (c *BinanceQlibClient) GetTradingStats() map[string]interface{} {
	if len(c.TradingHistory) == 0 {
		return map[string]interface{}{
			"total_trades": 0,
			"profitable_trades": 0,
			"total_pnl": 0.0,
			"win_rate": 0.0,
			"avg_profit": 0.0,
		}
	}
	
	totalPnL := 0.0
	profitableTrades := 0
	
	for _, trade := range c.TradingHistory {
		totalPnL += trade.PnL
		if trade.PnL > 0 {
			profitableTrades++
		}
	}
	
	winRate := float64(profitableTrades) / float64(len(c.TradingHistory)) * 100
	avgProfit := totalPnL / float64(len(c.TradingHistory))
	
	return map[string]interface{}{
		"total_trades":      len(c.TradingHistory),
		"profitable_trades": profitableTrades,
		"total_pnl":        totalPnL,
		"win_rate":         winRate,
		"avg_profit":       avgProfit,
	}
}

func main() {
	// Check for configuration
	configFile := "binance_trading_config.json"
	
	// Initialize client
	client := NewBinanceQlibClient("http://localhost:8080")
	
	// Try to load configuration
	if err := client.LoadConfig(configFile); err != nil {
		log.Printf("No config file found, creating default: %s", configFile)
		if err := client.SaveConfig(configFile); err != nil {
			log.Printf("Failed to save config: %v", err)
		}
	}
	
	// Print startup information
	fmt.Println("🚀 Binance Qlib Trading Client Started")
	fmt.Printf("📡 API Endpoint: %s\n", client.BaseURL)
	fmt.Printf("🎯 Watching: %v\n", client.Config.WatchSymbols)
	fmt.Printf("⚙️  Min Confidence: %.1f%%\n", client.Config.MinConfidence*100)
	fmt.Printf("💰 Max Positions: %d\n", client.Config.MaxPositions)
	fmt.Printf("🛑 Stop Loss: %.1f%%\n", client.Config.StopLossPercent*100)
	fmt.Printf("🎯 Take Profit: %.1f%%\n", client.Config.TakeProfitPercent*100)
	
	if client.Config.TradingEnabled {
		fmt.Println("🔥 LIVE TRADING ENABLED")
	} else {
		fmt.Println("📊 SIMULATION MODE - No real trades will be placed")
	}
	
	// Main trading loop
	for {
		fmt.Println("\n" + strings.Repeat("=", 80))
		
		signals, err := client.GetSignalsForSymbols(client.Config.WatchSymbols)
		if err != nil {
			log.Printf("❌ Error fetching signals: %v", err)
			time.Sleep(30 * time.Second)
			continue
		}
		
		// Process signals
		client.ProcessTradingSignals(signals)
		
		// Save trading history periodically
		if len(client.TradingHistory) > 0 {
			if err := client.SaveTradingHistory("binance_trading_history.json"); err != nil {
				log.Printf("Failed to save trading history: %v", err)
			}
		}
		
		// Print statistics every 10 minutes
		stats := client.GetTradingStats()
		if stats["total_trades"].(int) > 0 {
			fmt.Printf("\n📈 Trading Stats: %d trades, %.1f%% win rate, $%.2f total P&L\n",
				stats["total_trades"], stats["win_rate"], stats["total_pnl"])
		}
		
		// Wait before next check
		time.Sleep(30 * time.Second)
	}
}
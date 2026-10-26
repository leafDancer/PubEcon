import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
} from 'd3-force'
import { drag } from 'd3-drag'
import { select } from 'd3-selection'
import { zoom } from 'd3-zoom'
import type { NetworkEdge, NetworkNode } from '../types'
import { confidenceLabel, stageLabel } from '../lib'

interface SimNode extends NetworkNode {
  x?: number
  y?: number
  vx?: number
  vy?: number
  fx?: number | null
  fy?: number | null
}

interface SimLink extends Omit<NetworkEdge, 'source' | 'target'> {
  source: string | SimNode
  target: string | SimNode
}

const NODE_FILL: Record<string, string> = {
  high: '#104281',
  medium: '#2a78d6',
  low: '#86b6ef',
  unknown: '#b9c2bb',
}

function radius(node: NetworkNode): number {
  return Math.min(20, 5 + Math.sqrt(Math.max(node.papers, 1)) * 2.4)
}

export default function NetworkGraph({
  nodes,
  edges,
  compact = false,
}: {
  nodes: NetworkNode[]
  edges: NetworkEdge[]
  compact?: boolean
}) {
  const navigate = useNavigate()
  const svgRef = useRef<SVGSVGElement | null>(null)
  const canvasRef = useRef<HTMLDivElement | null>(null)
  const [hover, setHover] = useState<{ x: number; y: number; node: NetworkNode } | null>(null)

  useEffect(() => {
    const svgElement = svgRef.current
    const canvas = canvasRef.current
    if (!svgElement || !canvas || nodes.length === 0) return

    const width = compact ? 620 : 920
    const height = compact ? 320 : 560
    svgElement.setAttribute('viewBox', `0 0 ${width} ${height}`)
    const svg = select(svgElement)
    svg.selectAll('*').remove()

    const root = svg.append('g')
    const zoomBehavior = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.45, 3])
      .on('zoom', (event) => {
        root.attr('transform', event.transform)
      })
    if (!compact) svg.call(zoomBehavior)

    const simNodes: SimNode[] = nodes.map((node) => ({ ...node }))
    const simLinks: SimLink[] = edges.map((edge) => ({ ...edge }))
    const sparse = nodes.length < 55 && !compact
    const simulation = forceSimulation<SimNode>(simNodes)
      .force(
        'link',
        forceLink<SimNode, SimLink>(simLinks)
          .id((node) => node.id)
          .distance((link) =>
            Math.max(42, (sparse ? 132 : 76) - Math.min(link.weight, 8) * 4),
          )
          .strength(0.34),
      )
      .force('charge', forceManyBody().strength(compact ? -80 : sparse ? -300 : -135))
      .force('center', forceCenter(width / 2, height / 2))
      .force('collide', forceCollide<SimNode>().radius((node) => radius(node) + 7))
      .force('x', forceX(width / 2).strength(0.07))
      .force('y', forceY(height / 2).strength(0.07))
      .alpha(1)
      .alphaDecay(0.035)

    const links = root
      .append('g')
      .attr('class', 'ep-network-links')
      .selectAll('line')
      .data(simLinks)
      .join('line')
      .attr('stroke', '#8fa097')
      .attr('stroke-width', (link) => Math.min(4, 0.7 + Math.log2(link.weight + 1) * 0.9))
      .attr('stroke-opacity', 0.42)

    const nodeGroups = root
      .append('g')
      .attr('class', 'ep-network-nodes')
      .selectAll<SVGGElement, SimNode>('g')
      .data(simNodes)
      .join('g')
      .attr('class', (node) => `ep-network-node${node.is_center ? ' is-center' : ''}`)
      .style('cursor', 'pointer')
      .on('click', (_event, node) => navigate(`/authors/${node.id}`))
      .on('mouseenter', (event, node) => {
        const rect = canvas.getBoundingClientRect()
        setHover({
          x: event.clientX - rect.left,
          y: event.clientY - rect.top,
          node,
        })
      })
      .on('mousemove', (event, node) => {
        const rect = canvas.getBoundingClientRect()
        setHover({
          x: event.clientX - rect.left,
          y: event.clientY - rect.top,
          node,
        })
      })
      .on('mouseleave', () => setHover(null))

    nodeGroups
      .append('circle')
      .attr('r', (node) => radius(node))
      .attr('fill', (node) => NODE_FILL[node.confidence] ?? NODE_FILL.unknown)
      .attr('stroke', '#fafaf6')
      .attr('stroke-width', 1.6)

    const labelIds = new Set(
      [...nodes]
        .sort((left, right) => right.papers - left.papers)
        .slice(0, compact ? 0 : nodes.length < 55 ? 8 : 12)
        .map((node) => node.id),
    )
    for (const node of nodes) {
      if (node.is_center) labelIds.add(node.id)
    }

    nodeGroups
      .filter((node) => labelIds.has(node.id))
      .append('text')
      .attr('class', 'ep-network-label')
      .attr('y', (node) => radius(node) + 12)
      .attr('text-anchor', 'middle')
      .text((node) => node.name)

    const dragBehavior = drag<SVGGElement, SimNode>()
      .on('start', (event, node) => {
        if (!event.active) simulation.alphaTarget(0.25).restart()
        node.fx = node.x
        node.fy = node.y
      })
      .on('drag', (event, node) => {
        node.fx = event.x
        node.fy = event.y
      })
      .on('end', (event, node) => {
        if (!event.active) simulation.alphaTarget(0)
        node.fx = null
        node.fy = null
      })
    if (!compact) nodeGroups.call(dragBehavior)

    simulation.on('tick', () => {
      for (const node of simNodes) {
        const r = radius(node) + 5
        node.x = Math.max(r, Math.min(width - r, node.x ?? width / 2))
        node.y = Math.max(r, Math.min(height - r, node.y ?? height / 2))
      }
      links
        .attr('x1', (link) => (link.source as SimNode).x ?? 0)
        .attr('y1', (link) => (link.source as SimNode).y ?? 0)
        .attr('x2', (link) => (link.target as SimNode).x ?? 0)
        .attr('y2', (link) => (link.target as SimNode).y ?? 0)
      nodeGroups.attr('transform', (node) => `translate(${node.x ?? 0},${node.y ?? 0})`)
    })

    return () => {
      simulation.stop()
      svg.on('.zoom', null)
      svg.selectAll('*').remove()
    }
  }, [nodes, edges, compact, navigate])

  return (
    <div className={`ep-network-graph${compact ? ' is-compact' : ''}`}>
      <div className="ep-network-canvas" ref={canvasRef}>
        <svg
          ref={svgRef}
          role="img"
          aria-label={`Coauthor network with ${nodes.length} authors and ${edges.length} ties. Node colour shows career evidence confidence; node size shows papers in view.`}
        />
        {hover && (
          <div className="ep-chart-tip ep-network-tip" style={{ left: hover.x, top: hover.y }}>
            <strong>{hover.node.name}</strong>
            <span>{hover.node.institution ?? 'Institution not resolved'}</span>
            <span>
              {hover.node.papers} paper{hover.node.papers === 1 ? '' : 's'}
              {hover.node.shared ? `, ${hover.node.shared} shared` : ''}
            </span>
            <span>
              {stageLabel(hover.node.stage)}
              {hover.node.confidence !== 'unknown'
                ? `, ${confidenceLabel(hover.node.confidence)} confidence`
                : ''}
            </span>
          </div>
        )}
      </div>
      <div className="ep-legend ep-network-legend">
        <span className="ep-legend">
          <span className="ep-legend-dot is-high" /> High confidence
          <span className="ep-legend-dot is-medium" /> Medium
          <span className="ep-legend-dot is-low" /> Low
          <span className="ep-legend-dot is-unknown" /> No stage
        </span>
        <span className="ep-legend">Node size = papers in view. Edge width = shared papers.</span>
      </div>
    </div>
  )
}

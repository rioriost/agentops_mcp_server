class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/01/a1/eac916e6305265c293b9574571b65a24bc0ae4b9af689edec86462d118f3/agentops_mcp_server-0.0.9.tar.gz"
  sha256 "27ad0202dfc8be07754f45f35fc1108db6fd0f813a4a25fd28c1e7551d6d3e81"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end

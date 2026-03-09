class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/ff/8b/04ef2ca6731a4c94d591021a64c28dafdade50f187b9d89a828876d9b875/agentops_mcp_server-0.5.3.tar.gz"
  sha256 "4bda3d62da07ba3e72bbc35abd2689fb067ed7003f31d007fed01c1498030912"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
    prefix.install "README-jp.md"
    prefix.install "docs"
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
